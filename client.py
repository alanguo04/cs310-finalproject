#
# Client-side app to input the name of an image and then
# send this image off to AWS Rekognition for analysis.
#
import requests
import pathlib
import sys
import base64

# eliminate traceback so we just get error message:
sys.tracebacklimit = 0

#
# paste your web service endpoint here --- it should start with 
# https://, and should NOT end with a /. Here's a template where
# the stage used in API Gateway was "prod":
#

baseurl = "https://urv3reouhh.execute-api.us-east-2.amazonaws.com/prod"

url = baseurl + "/analysis"

filename = input("Image filename? ")

if not pathlib.Path(filename).is_file():
  print(f"**Error: file '{filename}' does not exist...")
  sys.exit(0)

infile = open(filename, "rb")
bytes = infile.read()
infile.close()

#
# now encode the pdf as base64. Note b64encode returns
# a bytes object, not a string. So then we have to convert
# (decode) the bytes -> string, and then we can serialize
# the string as JSON for upload to server:
#
data = base64.b64encode(bytes)
datastr = data.decode()

data = {
  "name": filename, 
  "bytes": datastr
}

print(f"Calling web service to analyze '{filename}'...")

response = requests.put(url, json=data)

#
# what did we get back?
#
if response.status_code != 200:
  # failed:
  print("**ERROR: failed with status code:", response.status_code)
  #
  if response.status_code == 500:  # we'll have an error message
    body = response.json()
    print("**Message:", body["message"])
  #
  sys.exit(0)

#
# deserialize and extract results:
#
body = response.json()

labels = body["data"]
numlabels = len(labels)
    
if numlabels == 0:
  print("Rekognition did not identify any labels...")
else:
  #
  # we have analysis results to output:
  #
  print(f"Rekognition identified {numlabels} labels:")
  
  for label in labels:
    name = label["label"]
    confidence = label["confidence"]
    print(f" {name} with {confidence}% confidence")
