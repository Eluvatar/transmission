#    Copyright 2014 Eluvatar
#
#    This file is part of Transmission.
#
#    Trawler is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    Trawler is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Transmission.  If not, see <http://www.gnu.org/licenses/>.

"""
    TODO docstring
"""

import zmq
import xml.etree.ElementTree as ET
import re
import json
import time
import threading
import Queue

from parser import api

class Unsubscription(Exception):
    pass

def regexify(event_text):
    """ Turns strings of the form 
            "@@(nation)@@ founded the region %%(region)%%." 
        into
            r'@@([a-z0-9\_\-]+)@@ founded the region %%([a-z0-9\_])%%\.'
        does not currently cover any replacements besides nation and region
        identifiers. (I.E. resolution names, nation titles, nation classes...)
    """
    # TODO support more substitutions
    replaced = event_text
    filters = [("@@(nation)@@","@@([a-z0-9\_\-]+)@@"),
    ("@@nation@@","@@[a-z0-9\_\-]+@@"),
    ("%%(region)%%","%%([a-z0-9\_]+)%%"),
    ("%%region%%","%%[a-z0-9\_]+%%")]
    for (from_str, to_str) in filters:
        replaced = replaced.replace(from_str, to_str)
    replaced = re.sub(r'\.$', '\.', replaced)
    return re.compile("^{0}$".format(replaced))

def _connect(port):
    url = "tcp://localhost:{0}".format(port)
    zsock = zmq.Context.instance().socket(zmq.DEALER)
    zsock.connect(url)
    return zsock

def oneshot(regex, port=6261):
    zsock = _connect(port)
    zsock.send(json.dumps({'subscribe':regex}))
    return zsock.recv()

def subscribe(regex_or_callback=None, regex=None, pattern=None, callback=None, callback_arg_type="object", port=6261, from_event_id=None):
    def inner(callback):
        if not callable(regex_or_callback) and not regex_or_callback is None:
            regex = regex_or_callback
        elif 'regex' not in locals():
            regex = None
        if not regex:
            if pattern:
                regex = regexify(pattern)
            else:
                raise ValueError("Must specify a pattern or regex!")
        if isinstance(regex, type(re.compile(''))):
            regex_re = regex
            regex_str = regex.pattern
        else:
            # TODO may need correction for unicode support
            regex_str = str(regex)
            regex_re = re.compile(regex_str)
        unsubscribed = threading.Event()
        def unsubscribe():
            unsubscribed.set()
        def callback_wrapper(event):
            if unsubscribed.is_set():
                return False
            try:
                callback(event)
                return True
            except Unsubscription:
                return False
        name = "Transmission Reception of {0}".format(regex_str)
        args = (regex_re, regex_str, callback_wrapper, callback_arg_type, port, from_event_id)
        worker = threading.Thread(target=_subscribe, name=name, args=args)
        worker.daemon = True
        worker.start()
        return unsubscribe
    if( callback ):
        return inner(callback)
    elif( callable(regex_or_callback) ):
        return inner(regex_or_callback)
    else:
        return inner

def _subscribe(regex_re, regex_str, callback, callback_arg_type, port, from_event_id):
    zsock = _connect(port)
    sub = json.dumps({'subscribe':regex_str})
    print "sub = {0}".format(sub)
    zsock.send(sub)
    timed_out = False
    queue = Queue.Queue()
    done = threading.Event()
    worker = threading.Thread(target=_worker, name="Transmission Reception Worker of {0}".format(regex_str), args=(queue,done))
    worker.daemon = True
    worker.start()
    while( not done.is_set() ):
        if( timed_out ):
            if( 0 == zsock.poll(60000) ):
                return
        s = zsock.recv()
        xml = ET.fromstring(s)
        acks = json.dumps({'ack':time.time()})
        if( xml.tag == "SUBSCRIBED" ):
            print s
            if( xml.text != regex_str ):
                print "bad subscription! {0} != {1}".format(xml.text, regex_str)
                return
            if( xml.get('last_event_id') is not None and from_event_id is not None):
                last_id = int(xml.get('last_event_id'))
                if last_id > from_event_id:
                    _enqueue(queue,_catchup,(from_event_id,last_id,regex_re,callback,callback_arg_type))
                    from_event_id = None
            timed_out = False
        elif( xml.tag == "TIMEOUT" ):
            timed_out = True
            # TODO log properly
            print "timed_out {0}".format(regex_str)
            zsock.send(sub)
        else:
            timed_out = 0
            zsock.send(acks)
            if( from_event_id is not None ):
                event_id = int(xml.get("id"))
                if event_id > from_event_id:
                    _enqueue(queue,_catchup,(from_event_id, event_id, regex_re, callback, callback_arg_type))
                    from_event_id = None
            _enqueue(queue,_receive,(xml, regex_re, callback, callback_arg_type))

def _enqueue(queue, fn, args):
    queue.put((fn,args))

def _worker(queue, done):
    keep_going = True
    while( keep_going ):
        fn, args = queue.get()
        keep_going = fn(*args)
    done.set()

def _catchup(from_event_id, event_id, regex_re, callback, callback_arg_type):
    for i in range(from_event_id, event_id, 200):
       xml = api.request({
           'q':'happenings',
           'sinceid':str(i),
           'beforeid':str(min(i+201,event_id)),
           'limit':'200'
       }, retries=10)
       assert xml is not None, "error getting happenings from %d to %d"%(i, i+201)
       events = xml.find("HAPPENINGS").findall("EVENT")
       events.reverse()
       for event in events:
           if _receive(event, regex_re, callback, callback_arg_type):
               pass
           else:
               return False
       return True

class Event(object):
    def __init__(self):
        self.group = None
        self.groups = None
        self.timestamp = None
        self.text = None
        self.id = None

def _receive(xml, regex_re, callback, callback_arg_type):
    text = xml.find("TEXT").text
    match = regex_re.search(text)
    if match:
        if( callback_arg_type == "xml" ):
            res = xml
        elif( callback_arg_type == "object" ):
            res = Event()
            res.id = int(xml.get("id"))
        res.group = match.group
        res.groups = match.groups
        res.timestamp = int(xml.find("TIMESTAMP").text)
        res.text = text
        return callback(res)

