import csv
import io
import shutil
import unittest
from unittest import mock

from flask import current_app
from flask import url_for
from tests.common import AppMixin
from tests.common import make_csv_file
from tests.common import RQWorkerMixin
from tests.common import TESTING_FILES_DIR

from flask_app import db
from flask_app import utils
from flask_app.app import API_URL_PREFIX
from flask_app.app import ClassifierStatusJson
from flask_app.app import ClassifierTestSetStatusJson
from flask_app.modeling.enqueue_jobs import Scheduler
from flask_app.settings import Settings


class ClassifierMixin(RQWorkerMixin, AppMixin):
    def setUp(self) -> None:
        super().setUp()
        # Create a classifer in the database
        self._clsf = db.Classifier.create(
            name="test_classifier", category_names=["up", "down"]
        )
        utils.Files.classifier_dir(self._clsf.classifier_id, ensure_exists=True)

        self._valid_training_contents = "\n".join(
            [
                f"{Settings.CONTENT_COL},{Settings.LABEL_COL}",
                "sky,up",
                "earth,down",
                "dimonds,down",
                "stars,up",
                "dead sea,down",
                "moon,up",
            ]
        )


class TestClassifiers(ClassifierMixin, unittest.TestCase):
    def test_get(self) -> None:
        url = API_URL_PREFIX + "/classifiers/"
        with current_app.test_client() as client:
            resp = client.get(url)
            self._assert_response_success(resp, url)
            resp_json = resp.get_json()
            self.assertIsInstance(resp_json, list)

            clsf_status = resp_json[0]
            expected_classifier_status = ClassifierStatusJson(
                classifier_id=self._clsf.classifier_id,
                classifier_name=self._clsf.name,
                category_names=self._clsf.category_names,
                status="not_begun",
                trained_by_openFraming=False,
                metrics=None,
            )
            self.assertDictEqual(clsf_status, dict(expected_classifier_status))

    def test_get_one_classifier(self) -> None:
        url = API_URL_PREFIX + f"/classifiers/{self._clsf.classifier_id}"
        with current_app.test_client() as client:
            resp = client.get(url)
            self._assert_response_success(resp, url)
            resp_json = resp.get_json()
            self.assertIsInstance(resp_json, dict)

            clsf_status = resp_json
            expected_classifier_status = ClassifierStatusJson(
                classifier_id=self._clsf.classifier_id,
                classifier_name=self._clsf.name,
                category_names=self._clsf.category_names,
                status="not_begun",
                trained_by_openFraming=False,
                metrics=None,
            )
            self.assertDictEqual(clsf_status, dict(expected_classifier_status))

    def test_trigger_training(self) -> None:
        # Mock the scheduler
        scheduler: Scheduler = current_app.scheduler
        scheduler.add_classifier_training: mock.MagicMock = mock.MagicMock(return_value=None)  # type: ignore

        test_url = (
            API_URL_PREFIX + f"/classifiers/{self._clsf.classifier_id}/training/file"
        )
        file_ = io.BytesIO(self._valid_training_contents.encode())
        with current_app.test_client() as client:
            output_dir = utils.Files.classifier_output_dir(self._clsf.classifier_id)
            dev_set_file = utils.Files.classifier_dev_set_file(self._clsf.classifier_id)
            train_set_file = utils.Files.classifier_train_set_file(
                self._clsf.classifier_id
            )

            res = client.post(test_url, data={"file": (file_, "labeled.csv")},)
            self._assert_response_success(res)

            # Assert response json
            expected_classifier_status = ClassifierStatusJson(
                classifier_id=self._clsf.classifier_id,
                classifier_name=self._clsf.name,
                category_names=self._clsf.category_names,
                status="training",
                trained_by_openFraming=False,
                metrics=None,
            )
            clsf_status = res.get_json()
            self.assertDictEqual(clsf_status, dict(expected_classifier_status))

        # Assert shceduler called
        scheduler.add_classifier_training.assert_called_with(
            classifier_id=self._clsf.classifier_id,
            labels=self._clsf.category_names,
            model_path=Settings.TRANSFORMERS_MODEL,
            dev_file=str(dev_set_file),
            train_file=str(train_set_file),
            cache_dir=str(Settings.TRANSFORMERS_CACHE_DIRECTORY),
            output_dir=str(output_dir),
        )

        # Assert files created
        self.assertTrue(dev_set_file.exists())
        self.assertTrue(train_set_file.exists())


class TestClassifiersTrainingFile(ClassifierMixin):
    def setUp(self) -> None:
        """Setup an "untrained" classifier."""
        super().setUp()
        dev_set_file = utils.Files.classifier_dev_set_file(self._clsf.classifier_id)
        train_set_file = utils.Files.classifier_train_set_file(self._clsf.classifier_id)

        # Copy over the files
        shutil.copy(TESTING_FILES_DIR / "classifiers" / "dev.csv", dev_set_file)
        shutil.copy(TESTING_FILES_DIR / "classifiers" / "train.csv", train_set_file)

        # Update the database
        self._clsf.train_set = db.LabeledSet()
        self._clsf.dev_set = db.LabeledSet()
        self._clsf.dev_set.save()
        self._clsf.train_set.save()
        self._clsf.save()

    def test_error_during_training(self) -> None:
        output_dir = utils.Files.classifier_output_dir(self._clsf.classifier_id)
        dev_set_file = utils.Files.classifier_dev_set_file(self._clsf.classifier_id)
        train_set_file = utils.Files.classifier_train_set_file(self._clsf.classifier_id)
        # Perform training, also will modify the database to indicate that it was
        # trained
        scheduler: Scheduler = current_app.scheduler
        # Note: This is a weak check because it is actually an error that can be caught
        # before the job is even queued(a file that doesn't exist).
        # But I don't have the time to figure out how to raise an error
        # in a forked process(which is what RQ workers are).
        scheduler.add_classifier_training(
            classifier_id=self._clsf.classifier_id,
            labels=self._clsf.category_names,
            model_path=Settings.TRANSFORMERS_MODEL,
            train_file=str(train_set_file / "SOMETHING THAT DOESNT EXIST"),
            dev_file=str(dev_set_file),
            cache_dir=str(Settings.TRANSFORMERS_CACHE_DIRECTORY),
            output_dir=str(output_dir),
            num_train_epochs=1.0,
        )
        self._burst_workers("classifiers")

        self._clsf = self._clsf.refresh()
        self.assertTrue(self._clsf.dev_set.refresh().error_encountered)  # type: ignore[union-attr]
        self.assertTrue(self._clsf.train_set.refresh().error_encountered)  # type: ignore[union-attr]

        with current_app.test_client() as client:
            get_clsf_url = url_for(
                "oneclassifier", classifier_id=self._clsf.classifier_id, _external=False
            )
            resp = client.get(get_clsf_url)
            self._assert_response_success(resp)
            self.assertEqual(resp.get_json()["status"], "error_encountered")

    def test_training_and_testing(self) -> None:
        with self.subTest("training classifier"):
            output_dir = utils.Files.classifier_output_dir(self._clsf.classifier_id)
            dev_set_file = utils.Files.classifier_dev_set_file(self._clsf.classifier_id)
            train_set_file = utils.Files.classifier_train_set_file(
                self._clsf.classifier_id
            )
            # Perform training, also will modify the database to indicate that it was
            # trained
            scheduler: Scheduler = current_app.scheduler
            scheduler.add_classifier_training(
                classifier_id=self._clsf.classifier_id,
                labels=self._clsf.category_names,
                model_path=Settings.TRANSFORMERS_MODEL,
                train_file=str(train_set_file),
                dev_file=str(dev_set_file),
                cache_dir=str(Settings.TRANSFORMERS_CACHE_DIRECTORY),
                output_dir=str(output_dir),
                num_train_epochs=1.0,
            )
            # Do the queued work
            assert self._burst_workers("classifiers")

            expected_classifier_status = dict(
                classifier_id=self._clsf.classifier_id,
                classifier_name=self._clsf.name,
                category_names=self._clsf.category_names,
                status="completed",
                trained_by_openFraming=False,
                # metrics is missing, on purpose
            )

            file_upload_url = API_URL_PREFIX + "/classifiers/"
            with current_app.test_client() as client:
                resp = client.get(file_upload_url)
            self._assert_response_success(resp, file_upload_url)

            resp_json = resp.get_json()
            assert isinstance(resp_json, list)
            clsf_status = resp_json[0]

            metrics = clsf_status.pop("metrics")
            self.assertDictEqual(clsf_status, expected_classifier_status)

            self.assertSetEqual(
                {"macro_f1_score", "accuracy", "macro_precision", "macro_recall",},
                set(metrics.keys()),
            )

            self.assertSetEqual(set(map(type, metrics.values())), {float})

        with self.subTest("get all test sets"):
            main_test_sets_url = (
                API_URL_PREFIX + f"/classifiers/{self._clsf.classifier_id}/test_sets/"
            )

            test_set_name = "my first test set ever!"
            req_json = {"test_set_name": test_set_name}

            resp = client.post(main_test_sets_url, json=req_json)

            # Assert successful response
            self._assert_response_success(resp, file_upload_url)

            # Assert test set created in db.
            # .get() should raise an error if nothing was created.
            created_test_set = self._clsf.test_sets.get()  # type: ignore

            # Assert the right response was returned
            resp_json = resp.get_json()
            expected_json = ClassifierTestSetStatusJson(
                test_set_id=created_test_set.id_,
                classifier_id=self._clsf.classifier_id,
                test_set_name=test_set_name,
                status="not_begun",
            )
            self.assertDictEqual(resp_json, dict(expected_json))

        with self.subTest("get one test set"):
            # Test the single-entity endpoint
            one_test_set_url = (
                API_URL_PREFIX
                + f"/classifiers/{self._clsf.classifier_id}/test_sets/{created_test_set.id_}"
            )

            one_test_set_resp = client.get(one_test_set_url)
            self._assert_response_success(one_test_set_resp, one_test_set_url)
            self.assertDictEqual(one_test_set_resp.get_json(), dict(expected_json))

            file_upload_url = (
                API_URL_PREFIX
                + f"/classifiers/{self._clsf.classifier_id}/test_sets/{created_test_set.id_}/file"
            )
            valid_test_file_table = [
                [f"{Settings.CONTENT_COL}"],
                ["galaxies"],
                ["ocean"],
                ["directions?"],
            ]

        with self.subTest("upload test set and trigger prediction"):
            file_to_upload = make_csv_file(valid_test_file_table)
            resp = client.post(
                file_upload_url, data={"file": (file_to_upload, "test.csv")}
            )
            self._assert_response_success(resp, file_upload_url)
            # Assert status changed to predicting
            expected_json = resp.get_json()
            self.assertEqual(expected_json.get("status"), "predicting")
            # Assert file was created
            test_set_file = utils.Files.classifier_test_set_file(
                self._clsf.classifier_id, created_test_set.id_
            )
            self.assertTrue(test_set_file.exists())

        with self.subTest("do prediction task and complete test set"):
            assert self._burst_workers("classifiers")
            # Assert the test results
            test_set_predictions_file = utils.Files.classifier_test_set_predictions_file(
                self._clsf.classifier_id, created_test_set.id_
            )
            self.assertTrue(test_set_predictions_file.exists())

            # Assert test set results make sense
            with test_set_predictions_file.open() as f:
                reader = csv.reader(f)
                rows = list(reader)
            self.assertListEqual(
                rows[0],
                [f"{Settings.CONTENT_COL}", f"{Settings.PREDICTED_LABEL_COL}",],
            )
            examples, predicted_labels = zip(*rows[1:])
            (expected_examples,) = zip(*valid_test_file_table[1:])
            self.assertSequenceEqual(examples, expected_examples)
            self.assertTrue(set(predicted_labels) <= {"up", "down"})

            # Assert the test set is reported as "completed" now
            resp = client.get(one_test_set_url)
            self._assert_response_success(resp, main_test_sets_url)

            resp_json = resp.get_json()
            self.assertEqual(resp_json["status"], "completed")

        # TODO: Figure out a way to easily mock a "trained classifier."
        # this will allow to break this giagantic function down into smaller ones,
        # and allow a unit test for when prediction task raises an Exception.


if __name__ == "__main__":
    unittest.main()