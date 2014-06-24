import zmq
import xml.etree.ElementTree as ET
import re
import json
import time
import threading

def _connect(port):
    url = "tcp://localhost:{0}".format(port)
    zsock = zmq.Context.instance().socket(zmq.DEALER)
    zsock.connect(url)
    return zsock

def oneshot(regex, port=6261):
    zsock = _connect(port)
    zsock.send(json.dumps({'subscribe':regex}))
    return zsock.recv()

def subscribe(regex, callback, port=6261):
    if regex is type(re.compile('')):
        regex_re = regex
        regex_str = regex.pattern
    else:
        regex_str = str(regex)
        regex_re = re.compile(regex_str)
    name = "Transmission Reception of {0}".format(regex_str)
    args = (regex_re,regex_str,callback, port)
    worker = threading.Thread(target=_subscribe, name=name, args=args)
    worker.daemon = True
    worker.start()

def _subscribe(regex_re, regex_str, callback, port):
    zsock = _connect(port)
    sub = json.dumps({'subscribe':regex_str})
    print "sub = {0}".format(sub)
    zsock.send(sub)
    timed_out = False
    while( not timed_out ):
        s = zsock.recv()
        xml = ET.fromstring(s)
        acks = json.dumps({'ack':time.time()})
        if( xml.tag == "TIMEOUT" ):
            timed_out = True
            print "timed_out {0}".format(regex_str)
        elif( regex_re.search(xml.find("TEXT").text) ):
            callback(xml)
            zsock.send(acks)
        else:
            zsock.send(acks)
