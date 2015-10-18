#!/usr/bin/python
#
#    Copyright 2015 Eluvatar
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
    Transmission is a daemon which watches the world happenings 
    (with a custom polling period)  and notifies subscribers of 
    happenings that match their regexes

    This is a simple daemon to log and show happenings it collects.
"""

import reception

from lxml import etree as ET

import argparse

parser = argparse.ArgumentParser(description="Log happenings")
parser.add_argument('-o','--output', metavar='FILE', help='a file to log XML events to')
parser.add_argument('-p','--port', metavar='PORT', help='a port number on which to talk to Transmission (default=6261)')

args = parser.parse_args()

if args.output:
    out = open(args.output,"a")

def xml(event):
    x = ET.Element("EVENT")
    x.set("id", str(event.id))
    ts = ET.SubElement(x, "TIMESTAMP")
    ts.text = str(event.timestamp)
    text = ET.SubElement(x, "TEXT")
    text.text = ET.CDATA(event.text)
    return x

@reception.subscribe(".*",port=6263)
def print_text_and_log_xml(e):
    print e.text
    if args.output:
        print >> out, ET.tostring(xml(e))

import time
while(True):
    time.sleep(600.0)
