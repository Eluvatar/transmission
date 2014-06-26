transmission
=====================

nationstates happenings subscription system

## Examples

### Transmission Daemon
```python
import transmission, logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

transmission.loop(user=YOUR_NATION_NAME_OR_URL_OR_EMAIL_OR_SOMETHING,port=6261)
```
The `user` argument should satisfy [the API terms of use](http://www.nationstates.net/pages/api.html#terms), and is required.
 
### Logger of All Happenings
```python
import reception
import xml.etree.ElementTree as ET

out=open("happenings.xml","a")

@reception.subscribe(".*")
def print_text_and_log_xml(xml):
    print xml.find("TEXT").text
    print >> out, ET.tostring(xml)

import time
while(True):
    time.sleep(600.0)
```


### Watcher of movement / WA membership happenings
```python
import reception
def print_event_text(xml):
    print xml.find("TEXT").text

EVENTS = ["@@nation@@ founded the region %%region%%.",
"@@nation@@ relocated from %%region%% to %%region%%.",
"@@nation@@ was admitted to the World Assembly.",
"@@nation@@ was founded in %%region%%.",
"@@nation@@ was refounded in %%region%%.",
"@@nation@@ ceased to exist.",
"@@nation@@ resigned from the World Assembly.",
"@@nation@@ was ejected from the WA for rule violations."]

for desc in EVENTS:
    reception.subscribe_pattern(desc,print_event_text)

import time
while(True):
    time.sleep(600.0)
```
