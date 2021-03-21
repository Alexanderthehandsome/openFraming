import requests
import pandas as pd

"""Classifier Part"""
# Will do later.
"""Topic Modelling Part"""
# /api/topic_models post
"""
data = {"topic_model_name": "something", "num_topics": 10, "notify_at_email": "vibs97@bu.edu", "language": "en"}
res = requests.post('http://0.0.0.0:5000/api/topic_models/', json=data)
print(res.text)
"""

# api/topic_models/1 get
"""
res = requests.get('http://0.0.0.0:5000/api/topic_models/1')
print(res.text)
"""

# api/topic_models/1/training/file/
"""
fil = open('testing_files/dev.csv', 'r')
print(pd.read_csv(fil, na_filter=False, header=None).to_numpy()[0])
data = {"file": fil}
res = requests.post('http://0.0.0.0:5000/api/topic_models/1/training/file', files=data)
print(res.text)
"""

# api/topic_models/1/topics/preview get
"""
res = requests.get('http://0.0.0.0:5000/api/topic_models/1/topics/preview')
print(res.text)
"""

# api/topic_models/1/topics/keywords get
# api/topic_models/1/topics_by_doc get
"""
# This is an excel file so won't be used here but in browser, you can download this.
res = requests.get('http://0.0.0.0:5000/api/topic_models/1/keywords?file_type=xlsx')
print(pd.read_excel(res.raw))
"""

# /topic_models/1/topics/names
"""
data = {"topic_names": ['my', 'name', 'is', 'vubh', '5', '6', '7', '8', '9', '10']}
res = requests.post('http://0.0.0.0:5000/api/topic_models/1/topics/names', json=data)
print(res.text)
""'