#!/usr/bin/env python

'''
A script to build a web site as a central repository for DMN decision service.
This is a flask version of DecisionCentral

SYNOPSIS
$ export FLASK_APP=DecisionCentral
$ python3 -m flask run


This script lets users upload Excel workbooks and XML files, which must comply to the DMN standard.
Once an Excel workbook or XML file has been uploaded and parsed successfully as DMN complient, this script will
1. Create a dedicated web page so that the user can interactively run/check their decision service
2. Create an API so that the user can use, programatically, their decision service
3. Create an OpenAPI yaml file documenting the created API

'''

# Import all the modules that make life easy
import io
import sys
import os
import datetime
import dateutil.parser, dateutil.tz
from flask import Flask, flash, abort, jsonify, url_for, request, render_template, redirect, send_file, Response
from werkzeug.utils import secure_filename
from urllib.parse import urlparse, urlencode, parse_qs, quote, unquote
from openpyxl import load_workbook
import pyDMNrules
import pySFeel
from pySFeel import SFeelLexer
import re
import csv
import ast
import copy
import logging

Excel_EXTENSIONS = {'xlsx', 'xlsm'}
ALLOWED_EXTENSIONS = {'xlsx', 'xlsm', 'xml', 'dmn'}

app = Flask(__name__)

decisionServices = {}        # The dictionary of currently defined Decision services
lexer = pySFeel.SFeelLexer()
parser = pySFeel.SFeelParser()

def mkOpenAPI(glossary, name, sheet):
    thisAPI = []
    thisAPI.append('openapi: 3.0.0')
    thisAPI.append('info:')
    if sheet is None:
        thisAPI.append('  title: Decision Service {}'.format(name))
    else:
        thisAPI.append('  title: Decision Service {} - Decision Table {}'.format(name, sheet))
    thisAPI.append('  version: 1.0.0')
    if ('X-Forwarded-Host' in request.headers) and ('X-Forwarded-Proto' in request.headers):
        thisAPI.append('servers:')
        thisAPI.append('  [')
        thisAPI.append('    "url":"{}://{}"'.format(request.headers['X-Forwarded-Proto'], request.headers['X-Forwarded-Host']))
        thisAPI.append('  ]')
    elif 'Host' in request.headers:
        thisAPI.append('servers:')
        thisAPI.append('  [')
        thisAPI.append('    "url":"{}"'.format(request.headers['Host']))
        thisAPI.append('  ]')
    elif 'Forwarded' in request.headers:
        forwards = request.headers['Forwarded'].split(';')
        origin = forwards[0].split('=')[1]
        thisAPI.append('servers:')
        thisAPI.append('  [')
        thisAPI.append('    "url":"{}"'.format(origin))
        thisAPI.append('  ]')
    thisAPI.append('paths:')
    if sheet is None:
        thisAPI.append('  /api/{}:'.format(quote(name)))
    else:
        thisAPI.append('  /api/{}_table/{}:'.format(quote(name), quote(sheet)))
    thisAPI.append('    post:')
    thisAPI.append('      summary: Use the {} Decision Service to make a decision based upon the passed data'.format(name))
    thisAPI.append('      operationId: decide')
    thisAPI.append('      requestBody:')
    thisAPI.append('        description: json structure with one tag per item of passed data')
    thisAPI.append('        content:')
    thisAPI.append('          application/json:')
    thisAPI.append('            schema:')
    thisAPI.append("              $ref: '#/components/schemas/decisionInputData'")
    thisAPI.append('        required: true')
    thisAPI.append('      responses:')
    thisAPI.append('        200:')
    thisAPI.append('          description: Success')
    thisAPI.append('          content:')
    thisAPI.append('            application/json:')
    thisAPI.append('              schema:')
    thisAPI.append("                $ref: '#/components/schemas/decisionOutputData'")
    thisAPI.append('components:')
    thisAPI.append('  schemas:')
    thisAPI.append('    decisionInputData:')
    thisAPI.append('      type: object')
    thisAPI.append('      properties:')
    for concept in glossary:
        if concept != 'Data':
            thisAPI.append('        "{}":'.format(concept))
            thisAPI.append('          type: array')
            thisAPI.append('          items:')
            thisAPI.append('            type: object')
            thisAPI.append('            properties:')
            for variable in glossary[concept]:
                thisAPI.append('              "{}":'.format(variable[len(concept)+1:]))
                thisAPI.append('                type: string')
        for variable in glossary[concept]:
            thisAPI.append('        "{}":'.format(variable))
            thisAPI.append('          type: string')
    thisAPI.append('    decisionOutputData:')
    thisAPI.append('      type: object')
    thisAPI.append('      properties:')
    thisAPI.append('        "Result":')
    thisAPI.append('          type: object')
    thisAPI.append('          properties:')
    for concept in glossary:
        for variable in glossary[concept]:
            thisAPI.append('            "{}":'.format(variable))
            thisAPI.append('              type: object')
            thisAPI.append('              additionalProperties:')
            thisAPI.append('                oneOf:')
            thisAPI.append('                  - type: string')
            thisAPI.append('                  - type: array')
            thisAPI.append('                    items:')
            thisAPI.append('                      type: string')
    thisAPI.append('        "Executed Rule":')
    thisAPI.append('          type: array')
    thisAPI.append('          items:')
    thisAPI.append('            additionalProperties:')
    thisAPI.append('              oneOf:')
    thisAPI.append('                - type: string')
    thisAPI.append('                - type: array')
    thisAPI.append('                  items:')
    thisAPI.append('                    type: string')
    thisAPI.append('        "Status":')
    thisAPI.append('          type: object')
    thisAPI.append('          properties:')
    thisAPI.append('            "errors":')
    thisAPI.append('              type: array')
    thisAPI.append('              items:')
    thisAPI.append('                type: string')
    thisAPI.append('      required: [')
    thisAPI.append('        "Result",')
    thisAPI.append('        "Executed Rule",')
    thisAPI.append('        "Status"')
    thisAPI.append('      ]')
    return '\n'.join(thisAPI)


def mkUploadOpenAPI():
    thisAPI = []
    thisAPI.append('openapi: 3.0.0')
    thisAPI.append('info:')
    thisAPI.append('  title: Decision Service file upload API')
    thisAPI.append('  version: 1.0.0')
    if ('X-Forwarded-Host' in request.headers) and ('X-Forwarded-Proto' in request.headers):
        thisAPI.append('servers:')
        thisAPI.append('  [')
        thisAPI.append('    "url":"{}://{}"'.format(request.headers['X-Forwarded-Proto'], request.headers['X-Forwarded-Host']))
        thisAPI.append('  ]')
    elif 'Host' in request.headers:
        thisAPI.append('servers:')
        thisAPI.append('  [')
        thisAPI.append('    "url":"{}"'.format(request.headers['Host']))
        thisAPI.append('  ]')
    elif 'Forwarded' in request.headers:
        forwards = request.headers['Forwarded'].split(';')
        origin = forwards[0].split('=')[1]
        thisAPI.append('servers:')
        thisAPI.append('  [')
        thisAPI.append('    "url":"{}"'.format(origin))
        thisAPI.append('  ]')
    thisAPI.append('paths:')
    thisAPI.append('  /upload:')
    thisAPI.append('    post:')
    thisAPI.append('      summary: Upload a file to DecisionCentral')
    thisAPI.append('      operationId: upload')
    thisAPI.append('      requestBody:')
    thisAPI.append('        description: json structure with one tag per item of passed data')
    thisAPI.append('        content:')
    thisAPI.append('          multipart/form-data:')
    thisAPI.append('            schema:')
    thisAPI.append("              $ref: '#/components/schemas/FileUpload'")
    thisAPI.append('        required: true')
    thisAPI.append('      responses:')
    thisAPI.append('        201:')
    thisAPI.append('          description: Item created')
    thisAPI.append('          content:')
    thisAPI.append('            text/html:')
    thisAPI.append('              schema:')
    thisAPI.append('                type: string')
    thisAPI.append('        400:')
    thisAPI.append('          description: Invalid input, object invalid')
    thisAPI.append('components:')
    thisAPI.append('  schemas:')
    thisAPI.append('    FileUpload:')
    thisAPI.append('      type: object')
    thisAPI.append('      properties:')
    thisAPI.append('        file:')
    thisAPI.append('          type: string')
    thisAPI.append('          format: binary')
    return '\n'.join(thisAPI)


def mkDeleteOpenAPI(name):
    thisAPI = []
    thisAPI.append('openapi: 3.0.0')
    thisAPI.append('info:')
    thisAPI.append('  title: Delete Decision Service API')
    thisAPI.append('  version: 1.0.0')
    if ('X-Forwarded-Host' in request.headers) and ('X-Forwarded-Proto' in request.headers):
        thisAPI.append('servers:')
        thisAPI.append('  [')
        thisAPI.append('    "url":"{}://{}"'.format(request.headers['X-Forwarded-Proto'], request.headers['X-Forwarded-Host']))
        thisAPI.append('  ]')
    elif 'Host' in request.headers:
        thisAPI.append('servers:')
        thisAPI.append('  [')
        thisAPI.append('    "url":"{}"'.format(request.headers['Host']))
        thisAPI.append('  ]')
    elif 'Forwarded' in request.headers:
        forwards = request.headers['Forwarded'].split(';')
        origin = forwards[0].split('=')[1]
        thisAPI.append('servers:')
        thisAPI.append('  [')
        thisAPI.append('    "url":"{}"'.format(origin))
        thisAPI.append('  ]')
    thisAPI.append('paths:')
    thisAPI.append('  /delete/{}:'.format(quote(name)))
    thisAPI.append('    get:')
    thisAPI.append('      summary: Delete a DecisionCentral Decision Service')
    thisAPI.append('      operationId: delete')
    thisAPI.append('      responses:')
    thisAPI.append('        200:')
    thisAPI.append('          description: Item deleted')
    thisAPI.append('          content:')
    thisAPI.append('            text/html:')
    thisAPI.append('              schema:')
    thisAPI.append('                type: string')
    thisAPI.append('        400:')
    thisAPI.append('          description: Invalid request')
    return '\n'.join(thisAPI)


def convertAtString(thisString):
    # Convert an @string
    (status, newValue) = parser.sFeelParse(thisString[2:-1])
    if 'errors' in status:
        return thisString
    else:
        return newValue


def convertInWeb(thisValue):
    # Convert a value (string) from the web form
    if not isinstance(thisValue, str):
        return thisValue
    try:
        newValue = ast.literal_eval(thisValue)
    except:
        newValue = thisValue
    return convertIn(newValue)


def convertIn(newValue):
    if isinstance(newValue, dict):
        for key in newValue:
            if isinstance(newValue[key], int):
                newValue[key] = float(newValue[key])
            elif isinstance(newValue[key], str) and (newValue[key][0:2] == '@"') and (newValue[key][-1] == '"'):
                newValue[key] = convertAtString(newValue[key])
            elif isinstance(newValue[key], dict) or isinstance(newValue[key], list):
                newValue[key] = convertIn(newValue[key])
    elif isinstance(newValue, list):
        for i in range(len(newValue)):
            if isinstance(newValue[i], int):
                newValue[i] = float(newValue[i])
            elif isinstance(newValue[i], str) and (newValue[i][0:2] == '@"') and (newValue[i][-1] == '"'):
                newValue[i] = convertAtString(newValue[i])
            elif isinstance(newValue[i], dict) or isinstance(newValue[i], list):
                newValue[i] = convertIn(newValue[i])
    elif isinstance(newValue, str) and (newValue[0:2] == '@"') and (newValue[-1] == '"'):
        newValue = convertAtString(newValue)
    return newValue


def convertOut(thisValue):
    if isinstance(thisValue, datetime.date):
        return '@"' + thisValue.isoformat() + '"'
    elif isinstance(thisValue, datetime.datetime):
        return '@"' + thisValue.isoformat(sep='T') + '"'
    elif isinstance(thisValue, datetime.time):
        return '@"' + thisValue.isoformat() + '"'
    elif isinstance(thisValue, datetime.timedelta):
        sign = ''
        duration = thisValue.total_seconds()
        if duration < 0:
            duration = -duration
            sign = '-'
        secs = duration % 60
        duration = int(duration / 60)
        mins = duration % 60
        duration = int(duration / 60)
        hours = duration % 24
        days = int(duration / 24)
        return '@"%sP%dDT%dH%dM%fS"' % (sign, days, hours, mins, secs)
    elif isinstance(thisValue, bool):
        if thisValue:
            return 'true'
        else:
            return 'false'
    elif isinstance(thisValue, int):
        sign = ''
        if thisValue < 0:
            thisValue = -thisValue
            sign = '-'
        years = int(thisValue / 12)
        months = (thisValue % 12)
        return '@"%sP%dY%dM"' % (sign, years, months)
    elif isinstance(thisValue, tuple) and (len(thisValue) == 4):
        (lowEnd, lowVal, highVal, highEnd) = thisValue
        return '@"' + lowEnd + str(lowVal) + ' .. ' + str(highVal) + highEnd
    elif thisValue is None:
        return 'null'
    elif isinstance(thisValue, dict):
        for item in thisValue:
            thisValue[item] = convertOut(thisValue[item])
        return thisValue
    elif isinstance(thisValue, list):
        for i in range(len(thisValue)):
            thisValue[i] = convertOut(thisValue[i])
        return thisValue
    else:
        return thisValue


@app.route('/', methods=['GET'])
def splash():
    message = '<html><head><title>Decision Central</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
    message += '<h1 style="text-align:center">Welcolme to Decision Central</h1>'
    message += '<h3 style="text-align:center">Your home for all your DMN Decision Services</h3>'
    message += '<div style="text-align:center;margin:auto"><b>Here you can create a Decision Service by simply'
    message += '<br/>uploading a DMN compatible Excel workbook or DMN compliant XML file</b></div>'
    message += '<br/><table width="90%" style="text-align:left;margin:auto;font-size:120%">'
    message += '<tr>'
    message += '<th style="padding-left:3ch">With each created Decision Service you get</th>'
    message += '<th>Available Decision Services</th>'
    message += '</tr>'
    message += '<tr><td>'
    message += '<ol>'
    message += '<li style="text-align:left">An API which you can use to test integration to you Decision Service'
    message += '<li style="text-align:left">A user interface where you can perform simple tests of your Decision Service'
    message += '<li style="text-align:left">A list of links to HTML renditions of the Decision Tables in your Decision Service'
    message += '<li style="text-align:left">A link to the Open API YAML file which describes you Decision Service'
    message += '</ol></td>'
    message += '<td>'
    for name in decisionServices:
        message += '<br/>'
        message += '<a href="{}">{}</a>'.format(url_for('show_decision_service', decisionServiceName=name), name)
    message += '</td>'
    message += '</tr>'
    message += '<tr>'
    message += '<td><p>Upload your DMN compatible Excel workook or DMN compliant XML file here</p>'
    message += '<form id="form" action ="{}" method="post" enctype="multipart/form-data">'.format(url_for('upload_file'))
    message += '<input id="file" type="file" name="file">'
    message += '<input id="submit" type="submit" value="Upload your workbook or XML file"></p>'
    message += '</form>'
    message += '</tr>'
    message += '<td></td>'
    message += '</table>'
    message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p>'.format(url_for('upload_api'), 'OpenAPI Specification for Decision Central file upload')
    message += '<p><b><u>WARNING:</u></b>This is not a production service. '
    message += 'This Azure service can be stopped/started/rebooted at any time. When it is rebooted everything is lost. You will need to re-upload you DMN compliant Excel workbooks in order to restore services. '
    message += 'There is no security/login requirements on this service. Anyone can upload their rules, using a Excel workbook or XML file with the same name as yours, thus replacing/corrupting your rules. '
    message += 'It is recommended that you obtain a copy of the source code from <a href="https://github.com/russellmcdonell/DecisionCentralAzure">GitHub</a> and run it on your own Azure App Service with appropriate security.'
    message += 'This in not production ready software. It is built, using <a href="https://pypi.org/project/pyDMNrules/">pyDMNrules</a>. '
    message += 'You can build production ready solutions using <b>pyDMNrules</b>, but this is not one of those solutions.</p></body></html>'
    return Response(response=message, status=200)


@app.route('/uploadapi', methods=['GET'])
def upload_api():
    # Assembling and send the HTML content
    message = '<html><head><title>Decision Service file upload Open API Specification</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
    message += '<h2 style="text-align:center">Open API Specification for Decision Service file upload</h2>'
    message += '<pre>'
    openapi = mkUploadOpenAPI()
    message += openapi
    message += '</pre>'
    message += '<p style="text-align:center"><b><a href="{}">Download the OpenAPI Specification for Decision Central file upload</a></b></p>'.format(url_for('download_upload_api'))
    message += '<div align="center">[curl {}:5000{}]</div>'.format(urlparse(request.base_url).hostname, url_for('download_upload_api'))
    message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
    return Response(response=message, status=200)


@app.route('/downloaduploadapi', methods=['GET'])
def download_upload_api():

    yaml = io.BytesIO(bytes(mkUploadOpenAPI(), 'utf-8'))

    return send_file(yaml, as_attachment=True, download_name='DecisionCentral_upload.yaml', mimetype='text/plain')


@app.route('/upload', methods=['POST'])
def upload_file():

    global decisionServices

    if 'file' not in request.files:
        message = '<html><head><title>Decision Central - No file part</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No file part found in the upload request</h2>'
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)
    file = request.files['file']
    if file.filename == '':
        message = '<html><head><title>Decision Central - No filename</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No filename found in the upload request</h2>'
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)
    name = os.path.basename(file.filename)
    (name, extn) = os.path.splitext(name)
    if extn[1:].lower() not in ALLOWED_EXTENSIONS:
        message = '<html><head><title>Decision Central - invalid file extension</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">Invalid file extension in the upload request</h2>'
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)
    decisionServiceName = name

    if extn[1:].lower() in Excel_EXTENSIONS:
        workbook = io.BytesIO()                 # Somewhere to store the DMN compliant Excel workbook
        file.save(workbook)
        # Create a Decision Service from the uploaded file
        try:                # Convert file to workbook
            wb = load_workbook(filename=workbook)
        except Exception as e:
            message = '<html><head><title>Decision Central - Bad Excel workbook</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
            message += '<h2 style="text-align:center">Bad Excel workbook</h2>'
            message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
            return Response(response=message, status=400)

        dmnRules = pyDMNrules.DMN()             # An empty Rules Engine
        status = dmnRules.use(wb)               # Add the rules from this DMN compliant Excel workbook
    else:
        xml = file.read()
        # Create a Decision Service from the uploaded file
        dmnRules = pyDMNrules.DMN()             # An empty Rules Engine
        status = dmnRules.useXML(xml)            # Add the rules from this DMN compliant XML file

    if 'errors' in status:
        message = '<html><head><title>Decision Central - Invalid DMN</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">There were Errors in your DMN rules</h2>'
        for i in range(len(status['errors'])):
            message += '<pre>{}</pre>'.format(status['errors'][i])
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    # Add this decision service to the list
    decisionServices[decisionServiceName] = copy.deepcopy(dmnRules)

    # Assembling and send the HTML content
    message = '<html><head><title>Decision Central - uploaded</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
    message += '<h2 style="text-align:center">Your DMN compatible Excel workbook or DMN compliant XML file has been successfully uploaded</h2>'
    message += '<h3 style="text-align:center">Your Decision Service has been created</h3>'
    message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
    return Response(response=message, status=201)


@app.route('/show/<decisionServiceName>', methods=['GET'])
def show_decision_service(decisionServiceName):

    global decisionServices

    if decisionServiceName not in decisionServices:
        message = '<html><head><title>Decision Central - no such Decision Service</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision service named {}</h2>'.format(decisionServiceName)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    dmnRules = decisionServices[decisionServiceName]
    glossary = dmnRules.getGlossary()
    glossaryNames = dmnRules.getGlossaryNames()
    sheets = dmnRules.getSheets()

    # Assembling and send the HTML content
    message = '<html><head><title>Decision Service {}</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'.format(decisionServiceName)
    message += '<h2 style="text-align:center">Your Decision Service {}</h2>'.format(decisionServiceName)
    message += '<table style="text-align:left;margin:auto;font-size:120%">'
    message += '<tr>'
    message += '<th>Test Decision Service {}</th>'.format(decisionServiceName)
    message += '<th>The Decision Services {} parts</th>'.format(decisionServiceName)
    message += '</tr>'

    # Create the user input form
    message += '<td>'
    message += '<form id="form" action ="{}" method="post">'.format(url_for('decision_service', decisionServiceName=decisionServiceName))
    message += '<h5>Enter values for these Variables</h5>'
    message += '<table style="border-spacing:0">'
    for concept in glossary:
        if concept != 'Data':
            message += '<tr><td>{}</td>'.format(concept)
            message += '<td colspan="3"><input type="text" name="{}" style="text-align:left;width:100%"></input></td></tr>'.format(concept)
        for variable in glossary[concept]:
            message += '<tr>'
            message += '<td></td><td style="text-align:right">{}</td>'.format(variable)
            message += '<td><input type="text" name="{}" style="text-align:left"></input></td>'.format(variable)
            if len(glossaryNames) > 1:
                (FEELname, value, attributes) = glossary[concept][variable]
                if len(attributes) == 0:
                    message += '<td style="text-align:left"></td>'
                else:
                    message += '<td style="text-align:left">{}</td>'.format(attributes[0])
            message += '</tr>'
    message += '</table>'
    message += '<h5>then click the "Make a Decision" button</h5>'
    message += '<input type="submit" value="Make a Decision"/></p>'
    message += '</form>'
    message += '</td>'

    # And links for the Decision Service parts
    message += '<td style="vertical-align:top">'
    message += '<br/>'
    message += '<a href="{}">{}</a>'.format(url_for('show_decision_service_part', decisionServiceName=decisionServiceName, part='/glossary'), 'Glossary')
    message += '<br/>'
    message += '<a href="{}">{}</a>'.format(url_for('show_decision_service_part', decisionServiceName=decisionServiceName,  part='/decision'), 'Decision Table'.replace(' ', '&nbsp;'))
    for sheet in sheets:
        message += '<br/>'
        message += '<a href="{}">{}</a>'.format(url_for('show_decision_service_part', decisionServiceName=decisionServiceName,  part=sheet), sheet.replace(' ', '&nbsp;'))
    message += '<br/>'
    message += '<br/>'
    message += '<a href="{}">{}</a>'.format(url_for('show_decision_service_part', decisionServiceName=decisionServiceName,  part='/api'), 'OpenAPI specification'.replace(' ', '&nbsp;'))
    message += '<br/>'
    message += '<br/>'
    message += '<br/>'
    message += '<br/>'
    message += '<br/>'
    message += '<a href="{}">Delete the {} Decision Service</a>'.format(url_for('delete_decision_service', decisionServiceName=decisionServiceName), decisionServiceName.replace(' ', '&nbsp;'))
    message += '<br/>'
    message += '<a href="{}">API for deleting the {} Decision Service</a>'.format(url_for('show_delete_decision_service', decisionServiceName=decisionServiceName), decisionServiceName.replace(' ', '&nbsp;'))
    message += '</td>'
    message += '</tr></table>'
    message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
    return Response(response=message, status=200)


@app.route('/show_delete/<decisionServiceName>/', methods=['GET'])
def show_delete_decision_service(decisionServiceName):
    # Assembling and send the HTML content
    message = '<html><head><title>Delete Decision Service {} Open API Specification</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'.format(decisionServiceName)
    message += '<h2 style="text-align:center">Open API Specification for deleting the {} Decision Service</h2>'.format(decisionServiceName)
    message += '<pre>'
    openapi = mkDeleteOpenAPI(decisionServiceName)
    message += openapi
    message += '</pre>'
    message += '<p style="text-align:center"><b><a href="{}">Download the OpenAPI Specification for deleting the {} Decision Service</a></b></p>'.format(url_for('download_delete_decision_service_api', decisionServiceName=decisionServiceName), decisionServiceName)
    message += '<div style="text-align:center;margin:auto">[curl {}:5000{}]</div>'.format(url_for('download_delete_decision_service_api', decisionServiceName=decisionServiceName))
    message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('show_decision_service', decisionServiceName=decisionServiceName), ('Return to Decision Service ' + decisionServiceName).replace(' ','&nbsp;'))
    return Response(response=message, status=200)

@app.route('/show/<decisionServiceName>/<part>', methods=['GET'])
def show_decision_service_part(decisionServiceName, part):

    global decisionServices

    if decisionServiceName not in decisionServices:
        message = '<html><head><title>Decision Central - no such Decision Service</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision service named {}</h2>'.format(decisionServiceName)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    dmnRules = decisionServices[decisionServiceName]
    if part == 'glossary':          # Show the Glossary for this Decision Service
        glossaryNames = dmnRules.getGlossaryNames()
        glossary = dmnRules.getGlossary()

        # Assembling and send the HTML content
        message = '<html><head><title>Decision Service {} Glossary</title><link ref="icon" href="data:,"></head><body style="font-size:120%">'.format(decisionServiceName)
        message += '<h2 style="text-align:center">The Glossary for the {} Decision Service</h2>'.format(decisionServiceName)
        message += '<div style="width:25%;background-color:black;color:white">{}</div>'.format('Glossary - ' + glossaryNames[0])
        message += '<table style="border-collapse:collapse;border:2px solid"><tr>'
        message += '<th style="border:2px solid;background-color:LightSteelBlue">Variable</th><th style="border:2px solid;background-color:LightSteelBlue">Business Concept</th><th style="border:2px solid;background-color:LightSteelBlue">Attribute</th>'
        if len(glossaryNames) > 1:
            for i in range(1, len(glossaryNames)):
                message += '<th style="border:2px solid;background-color:DarkSeaGreen">{}</th>'.format(glossaryNames[i])
        message += '</tr>'
        for concept in glossary:
            rowspan = len(glossary[concept].keys())
            firstRow = True
            for variable in glossary[concept]:
                message += '<tr><td style="border:2px solid">{}</td>'.format(variable)
                (FEELname, value, attributes) = glossary[concept][variable]
                dotAt = FEELname.find('.')
                if dotAt != -1:
                    FEELname = FEELname[dotAt + 1:]
                if firstRow:
                    message += '<td rowspan="{}" style="border:2px solid">{}</td>'.format(rowspan, concept)
                    firstRow = False
                message += '<td style="border:2px solid">{}</td>'.format(FEELname)
                if len(glossaryNames) > 1:
                    for i in range(len(glossaryNames) - 1):
                        if i < len(attributes):
                            message += '<td style="border:2px solid">{}</td>'.format(attributes[i])
                        else:
                            message += '<td style="border:2px solid"></td>'
                message += '</tr>'
        message += '</table>'
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('show_decision_service', decisionServiceName=decisionServiceName), ('Return to Decision Service ' + decisionServiceName).replace(' ','&nbsp;'))
        return Response(response=message, status=200)
    elif part == 'decision':            # Show the Decision for this Decision Service
        decisionName = dmnRules.getDecisionName()
        decision = dmnRules.getDecision()

        # Assembling and send the HTML content
        message = '<html><head><title>Decision Service {} Decision Table</title><link ref="icon" href="data:,"></head><body style="font-size:120%">'.format(decisionServiceName)
        message += '<h2 style="text-align:center">The Decision Table for the {} Decision Service</h2>'.format(decisionServiceName)
        message += '<div style="width:25%;background-color:black;color:white">{}</div>'.format('Decision - ' + decisionName)
        message += '<table style="border-collapse:collapse;border:2px solid">'
        inInputs = True
        inDecide = False
        for i in range(len(decision)):
            message += '<tr>'
            for j in range(len(decision[i])):
                if i == 0:
                    if decision[i][j] == 'Decisions':
                        inInputs = False
                        inDecide = True
                    if inInputs:
                        message += '<th style="border:2px solid;background-color:DodgerBlue">{}</th>'.format(decision[i][j])
                    elif inDecide:
                        message += '<th style="border:2px solid;background-color:LightSteelBlue">{}</th>'.format(decision[i][j])
                    else:
                        message += '<th style="border:2px solid;background-color:DarkSeaGreen">{}</th>'.format(decision[i][j])
                    if decision[i][j] == 'Execute Decision Tables':
                        inDecide = False
                else:
                    if decision[i][j] == '-':
                        message += '<td style="text-align:center;border:2px solid">{}</td>'.format(decision[i][j])
                    else:
                        message += '<td style="border:2px solid">{}</td>'.format(decision[i][j])
            message += '</tr>'
        message += '</table>'
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('show_decision_service', decisionServiceName=decisionServiceName), ('Return to Decision Service ' + decisionServiceName).replace(' ','&nbsp;'))
        return Response(response=message, status=200)
    elif part == 'api':         # Show the OpenAPI definition for this Decision Service
        glossary = dmnRules.getGlossary()

        # Assembling and send the HTML content
        message = '<html><head><title>Decision Service {} Open API Specification</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'.format(decisionServiceName)
        message += '<h2 style="text-align:center">Open API Specification for the {} Decision Service</h2>'.format(decisionServiceName)
        message += '<pre>'
        openapi = mkOpenAPI(glossary, decisionServiceName, None)
        message += openapi
        message += '</pre>'
        message += '<p style="text-align:center"><b><a href="{}">Download the OpenAPI Specification for Decision Service {}</a></b></p>'.format(url_for('download_decision_service_api', decisionServiceName=decisionServiceName),  decisionServiceName)
        message += '<div style="text-align:center;margin:auto">[curl {}:5000{}]</div>'.format(url_for('download_decision_service_api', decisionServiceName=decisionServiceName))
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('show_decision_service', decisionServiceName=decisionServiceName), ('Return to Decision Service ' + decisionServiceName).replace(' ','&nbsp;'))
        return Response(response=message, status=200)
    else:                       # Show a worksheet
        sheets = dmnRules.getSheets()
        if part not in sheets:
            logging.warning('GET: {} not in sheets'.format(part))
            message = '<html><head><title>Decision Central - no such Decision Table</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
            message += '<h2 style="text-align:center">No decision table named {}</h2>'.format(part)
            message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
            return Response(response=message, status=400)
        glossary = dmnRules.getTableGlossary(part)
        glossaryNames = dmnRules.getGlossaryNames()

        # Assembling and send the HTML content
        message = '<html><head><title>Decision Service {} sheet "{}"</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'.format(decisionServiceName, part)
        message += '<h2 style="text-align:center">The Decision sheet "{}" for Decision Service {}</h2>'.format(part, decisionServiceName)
        message += sheets[part]
        message += '<br/>'

        # Create the user input form
        message += '<form id="form" action ="{}" method="post">'.format(url_for('decision_service_table', decisionServiceName=decisionServiceName, sheet=part))
        message += '<h5>Enter values for these Variables</h5>'
        message += '<table style="border-spacing:0">'
        for concept in glossary:
            if concept != 'Data':
                message += '<tr><td>{}</td>'.format(concept)
                message += '<td colspan="3"><input type="text" name="{}" style="text-align:left;width:100%"></input></td></tr>'.format(concept)
            for variable in glossary[concept]:
                message += '<tr>'
                message += '<td></td><td style="text-align:right">{}</td>'.format(variable)
                message += '<td><input type="text" name="{}" style="text-align:left"></input></td>'.format(variable)
                if len(glossaryNames) > 1:
                    (FEELname, value, attributes) = glossary[concept][variable]
                    if len(attributes) == 0:
                        message += '<td style="text-align:left"></td>'
                    else:
                        message += '<td style="text-align=left">{}</td>'.format(attributes[0])
                message += '</tr>'
        message += '</table>'
        message += '<h5>then click the "Make a Decision" button</h5>'
        message += '<input type="submit" value="Make a Decision"/></p>'
        message += '</form>'

        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p>'.format(url_for('show_decision_service_part_api', decisionServiceName=decisionServiceName,  sheet=part), 'OpenAPI specification'.replace(' ', '&nbsp;'))
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('show_decision_service', decisionServiceName=decisionServiceName), ('Return to Decision Service ' + decisionServiceName).replace(' ','&nbsp;'))
        return Response(response=message, status=200)

@app.route('/show_api/<decisionServiceName>/<sheet>', methods=['GET'])
def show_decision_service_part_api(decisionServiceName, sheet):

    global decisionServices

    if decisionServiceName not in decisionServices:
        message = '<html><head><title>Decision Central - no such Decision Service</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision service named {}</h2>'.format(decisionServiceName)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    dmnRules = decisionServices[decisionServiceName]
    sheets = dmnRules.getSheets()
    if sheet not in sheets:
        logging.warning('GET: {} not in sheets'.format(part))
        message = '<html><head><title>Decision Central - no such Decision Table</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision table named {}</h2>'.format(part)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)
    glossary = dmnRules.getTableGlossary(sheet)

    # Assembling and send the HTML content
    message = '<html><head><title>Decision Service {} Open API Specification for {} Decision Table</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'.format(decisionServiceName, sheet)
    message += '<h2 style="text-align:center">Open API Specification for the Decision Table {} in the Decision Service {}</h2>'.format(sheet, decisionServiceName)
    message += '<pre>'
    openapi = mkOpenAPI(glossary, decisionServiceName, sheet)
    message += openapi
    message += '</pre>'
    message += '<p style="text-align:center"><b><a href="{}">Download the OpenAPI Specification for Decision Table {} in Decision Service {}</a></b></p>'.format(url_for('download_decision_service_table_api', decisionServiceName=decisionServiceName, sheet=sheet),  sheet, decisionServiceName)
    message += '<div style="text-align:center;margin:auto">[curl {}:5000{}]</div>'.format(url_for('download_decision_service_table_api', decisionServiceName=decisionServiceName, sheet=sheet))
    message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('show_decision_service', decisionServiceName=decisionServiceName), ('Return to Decision Service ' + decisionServiceName).replace(' ','&nbsp;'))
    return Response(response=message, status=200)


@app.route('/download/<decisionServiceName>', methods=['GET'])
def download_decision_service_api(decisionServiceName):
    if decisionServiceName not in decisionServices:
        message = '<html><head><title>Decision Central - no such Decision Service</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision service named {}</h2>'.format(decisionServiceName)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    dmnRules = decisionServices[decisionServiceName]

    dmnRules = decisionServices[decisionServiceName]
    glossary = dmnRules.getGlossary()
    yaml = io.BytesIO(bytes(mkOpenAPI(glossary, decisionServiceName, None), 'utf-8'))
    name = secure_filename(decisionServiceName + '.yaml')

    return send_file(yaml, as_attachment=True, download_name=name, mimetype='text/plain')


@app.route('/download/<decisionServiceName>/<sheet>', methods=['GET'])
def download_decision_service_table_api(decisionServiceName, sheet):
    if decisionServiceName not in decisionServices:
        message = '<html><head><title>Decision Central - no such Decision Service</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision service named {}</h2>'.format(decisionServiceName)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    dmnRules = decisionServices[decisionServiceName]

    dmnRules = decisionServices[decisionServiceName]
    sheets = dmnRules.getSheets()
    if sheet not in sheets:
        logging.warning('GET: {} not in sheets'.format(part))
        message = '<html><head><title>Decision Central - no such Decision Table</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision table named {}</h2>'.format(part)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)
    glossary = dmnRules.getTableGlossary(sheet)
    yaml = io.BytesIO(bytes(mkOpenAPI(glossary, decisionServiceName, sheet), 'utf-8'))
    name = secure_filename(decisionServiceName + '_' + sheet + '.yaml')

    return send_file(yaml, as_attachment=True, download_name=name, mimetype='text/plain')


@app.route('/download_delete/<decisionServiceName>', methods=['GET'])
def download_delete_decision_service_api(decisionServiceName):
    if decisionServiceName not in decisionServices:
        message = '<html><head><title>Decision Central - no such Decision Service</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision service named {}</h2>'.format(decisionServiceName)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    yaml = io.BytesIO(bytes(mkDeleteOpenAPI(decisionServiceName), 'utf-8'))
    name = secure_filename(decisionServiceName + '_delete.yaml')

    return send_file(yaml, as_attachment=True, download_name=name, mimetype='text/plain')


@app.route('/delete/<decisionServiceName>', methods=['GET'])
def delete_decision_service(decisionServiceName):

    global decisionServices

    if decisionServiceName not in decisionServices:
        message = '<html><head><title>Decision Central - no such Decision Service</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision service named {}</h2>'.format(decisionServiceName)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    del decisionServices[decisionServiceName]

    # Assembling and send the HTML content
    message = '<html><head><title>Decision Central - deleted</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
    message += '<h2 style="text-align:center">Your DMN Decision Service {} has been deleted.</h2>'.format(decisionServiceName)
    message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
    return Response(response=message, status=200)


@app.route('/api/<decisionServiceName>', methods=['POST'])
def decision_service(decisionServiceName):

    global decisionServices

    if decisionServiceName not in decisionServices:
        message = '<html><head><title>Decision Central - no such Decision Service</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision service named {}</h2>'.format(decisionServiceName)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    dmnRules = decisionServices[decisionServiceName]

    data = {}
    if request.content_type == 'application/x-www-form-urlencoded':         # From the web page
        for variable in request.form:
            value = request.form[variable].strip()
            if value != '':
                data[variable] = convertInWeb(value)
    else:
        data = request.get_json()
        for variable in data:
            value = data[variable]
            data[variable] = convertIn(value)

    # Check if JSON or HTML response required
    wantsJSON = False
    for i in range(len(request.accept_mimetypes)):
        (mimeType, quality) = request.accept_mimetypes[i]
        if mimeType == 'application/json':
            wantsJSON = True

    # Now make the decision
    (status, newData) = dmnRules.decide(data)
    if 'errors' in status:
        if wantsJSON:
            newData = {}
            newData['Result'] = {}
            newData['Executed Rule'] = []
            newData['Status'] = status
            return jsonify(newData)
        else:
            message = '<html><head><title>Decision Central - bad status from Decision Service {}</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'.format(decisionServiceName)
            message += '<h2 style="text-align:center">Your Decision Service {} returned a bad status</h2>'.format(decisionServiceName)
            for i in range(len(status['errors'])):
                message += '<pre>{}</pre>'.format(status['errors'][i])
            message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
            return Response(response=message, status=400)

    if wantsJSON:
        # Return the results dictionary
        # The structure of the returned data varies depending upon the Hit Policy of the last executed Decision Table
        # We don't have the Hit Policy, but we can work it out
        returnData = {}
        returnData['Executed Rule'] = []
        if isinstance(newData, list):
            for i in range(len(newData)):
                if isinstance(newData[i]['Executed Rule'], list):           # The last executed Decision Table was RULE ORDER, OUTPUT ORDER or COLLECTION
                    for j in range(len(newData[i]['Executed Rule'])):
                        returnData['Executed Rule'].append([])
                        (executedDecision, decisionTable,ruleId) = newData[i]['Executed Rule'][j]
                        returnData['Executed Rule'][-1].append(executedDecision)
                        returnData['Executed Rule'][-1].append(decisionTable)
                        returnData['Executed Rule'][-1].append(ruleId)
                else:
                    returnData['Executed Rule'].append([])
                    (executedDecision, decisionTable,ruleId) = newData[i]['Executed Rule']
                    returnData['Executed Rule'][-1].append(executedDecision)
                    returnData['Executed Rule'][-1].append(decisionTable)
                    returnData['Executed Rule'][-1].append(ruleId)
            newData = newData[-1]
        elif 'Executed Rule' in newData:
            (executedDecision, decisionTable,ruleId) = newData['Executed Rule']
            returnData['Executed Rule'].append(executedDecision)
            returnData['Executed Rule'].append(decisionTable)
            returnData['Executed Rule'].append(ruleId)
        returnData['Result'] = {}
        for variable in newData['Result']:
            value = newData['Result'][variable]
            returnData['Result'][variable] = convertOut(value)
        returnData['Status'] = status
        return jsonify(returnData)
    else:
        # Assembling the HTML content
        message = '<html><head><title>The decision from Decision Service {}</title><link rel="icon" href="data:,"></head><body>'.format(decisionServiceName)
        message += '<h1>Decision Service {}</h1>'.format(decisionServiceName)
        message += '<h2>The Decision</h2>'
        message += '<table style="width:70%">'
        message += '<tr><th style="border:2px solid">Variable</th>'
        message += '<th style="border:2px solid">Value</th></tr>'
        if isinstance(newData, list):
            newData = newData[-1]
        for variable in newData['Result']:
            if newData['Result'][variable] == '':
                continue
            message += '<tr><td style="border:2px solid">{}</td>'.format(variable)
            message += '<td style="border:2px solid">{}</td></tr>'.format(str(newData['Result'][variable]))
        message += '</table>'
        message += '<h2>The Deciders</h2>'
        message += '<table style="width:70%">'
        message += '<tr><th style="border:2px solid">Executed Decision</th>'
        message += '<th style="border:2px solid">Decision Table</th>'
        message += '<th style="border:2px solid">Rule Id</th></tr>'
        if isinstance(newData['Executed Rule'], list):           # The last executed Decision Table was RULE ORDER, OUTPUT ORDER or COLLECTION
            for j in range(len(newData['Executed Rule'])):
                (executedDecision, decisionTable,ruleId) = newData['Executed Rule'][j]
                message += '<tr><td style="border:2px solid">{}</td>'.format(executedDecision)
                message += '<td style="border:2px solid">{}</td>'.format(decisionTable)
                message += '<td style="border:2px solid">{}</td></tr>'.format(ruleId)
                message += '<tr>'
        else:
            (executedDecision, decisionTable,ruleId) = newData['Executed Rule']
            message += '<tr><td style="border:2px solid">{}</td>'.format(executedDecision)
            message += '<td style="border:2px solid">{}</td>'.format(decisionTable)
            message += '<td style="border:2px solid">{}</td></tr>'.format(ruleId)
            message += '<tr>'
        message += '</table>' 
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('show_decision_service', decisionServiceName=decisionServiceName), ('Return to Decision Service ' + decisionServiceName).replace(' ','&nbsp;'))
        message += '<p style="text-align:center"><b><a href="/">{}</a></b></p></body></html>'.format('Return to Decision Central')
        return Response(response=message, status=200)

@app.route('/api/<decisionServiceName>_table/<sheet>', methods=['POST'])
def decision_service_table(decisionServiceName, sheet):

    global decisionServices

    if decisionServiceName not in decisionServices:
        message = '<html><head><title>Decision Central - no such Decision Service</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'
        message += '<h2 style="text-align:center">No decision service named {}</h2>'.format(decisionServiceName)
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
        return Response(response=message, status=400)

    dmnRules = decisionServices[decisionServiceName]

    data = {}
    if request.content_type == 'application/x-www-form-urlencoded':         # From the web page
        for variable in request.form:
            value = request.form[variable].strip()
            if value != '':
                data[variable] = convertInWeb(value)
    else:
        data = request.get_json()
        for variable in data:
            value = data[variable]
            data[variable] = convertIn(value)

    # Check if JSON or HTML response required
    wantsJSON = False
    for i in range(len(request.accept_mimetypes)):
        (mimeType, quality) = request.accept_mimetypes[i]
        if mimeType == 'application/json':
            wantsJSON = True

    # Now make the decision
    (status, newData) = dmnRules.decideTables(data, [sheet])
    if 'errors' in status:
        if wantsJSON:
            newData = {}
            newData['Result'] = {}
            newData['Executed Rule'] = []
            newData['Status'] = status
            return jsonify(newData)
        else:
            message = '<html><head><title>Decision Central - bad status from Decision Service {}</title><link rel="icon" href="data:,"></head><body style="font-size:120%">'.format(decisionServiceName)
            message += '<h2 style="text-align:center">Your Decision Service {} returned a bad status</h2>'.format(decisionServiceName)
            for i in range(len(status['errors'])):
                message += '<pre>{}</pre>'.format(status['errors'][i])
            message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('splash'), 'Return to Decision Central')
            return Response(response=message, status=400)

    if wantsJSON:
        # Return the results dictionary
        # The structure of the returned data varies depending upon the Hit Policy of the last executed Decision Table
        # We don't have the Hit Policy, but we can work it out
        returnData = {}
        returnData['Executed Rule'] = []
        if isinstance(newData, list):
            for i in range(len(newData)):
                if isinstance(newData[i]['Executed Rule'], list):           # The last executed Decision Table was RULE ORDER, OUTPUT ORDER or COLLECTION
                    for j in range(len(newData[i]['Executed Rule'])):
                        returnData['Executed Rule'].append([])
                        (executedDecision, decisionTable, ruleId) = newData[i]['Executed Rule'][j]
                        returnData['Executed Rule'][-1].append(executedDecision)
                        returnData['Executed Rule'][-1].append(decisionTable)
                        returnData['Executed Rule'][-1].append(ruleId)
                else:
                    returnData['Executed Rule'].append([])
                    (executedDecision, decisionTable, ruleId) = newData[i]['Executed Rule']
                    returnData['Executed Rule'][-1].append(executedDecision)
                    returnData['Executed Rule'][-1].append(decisionTable)
                    returnData['Executed Rule'][-1].append(ruleId)
            if len(newData) > 0:
                newData = newData[-1]
        else:
            if isinstance(newData['Executed Rule'], list):           # The last executed Decision Table was RULE ORDER, OUTPUT ORDER or COLLECTION
                for i in range(len(newData['Executed Rule'])):
                    returnData['Executed Rule'].append([])
                    (executedDecision, decisionTable, ruleId) = newData['Executed Rule'][i]
                    returnData['Executed Rule'][-1].append(executedDecision)
                    returnData['Executed Rule'][-1].append(decisionTable)
                    returnData['Executed Rule'][-1].append(ruleId)
            else:
                (executedDecision, decisionTable, ruleId) = newData['Executed Rule']
                returnData['Executed Rule'].append(executedDecision)
                returnData['Executed Rule'].append(decisionTable)
                returnData['Executed Rule'].append(ruleId)
        returnData['Result'] = {}
        for variable in newData['Result']:
            value = newData['Result'][variable]
            returnData['Result'][variable] = convertOut(value)
        returnData['Status'] = status
        return jsonify(returnData)
    else:
        # Assembling the HTML content
        message = '<html><head><title>The decision from Decision Service {}, Decision Table {}</title><link rel="icon" href="data:,"></head><body>'.format(decisionServiceName, sheet)
        message += '<h1>Decision Service {}, Decision Table {}</h1>'.format(decisionServiceName, sheet)
        message += '<h2>The Decision</h2>'
        message += '<table style="width:70%">'
        message += '<tr><th style="border:2px solid">Variable</th>'
        message += '<th style="border:2px solid">Value</th></tr>'
        if isinstance(newData, list) and (len(newData) > 0):
            newData = newData[-1]
        for variable in newData['Result']:
            if newData['Result'][variable] == '':
                continue
            message += '<tr><td style="border:2px solid">{}</td>'.format(variable)
            message += '<td style="border:2px solid">{}</td></tr>'.format(str(newData['Result'][variable]))
        message += '</table>'
        message += '<h2>The Deciders</h2>'
        message += '<table style="width:70%">'
        message += '<tr><th style="border:2px solid">Executed Decision</th>'
        message += '<th style="border:2px solid">Decision Table</th>'
        message += '<th style="border:2px solid">Rule Id</th></tr>'
        if isinstance(newData['Executed Rule'], list):           # The last executed Decision Table was RULE ORDER, OUTPUT ORDER or COLLECTION
            for j in range(len(newData['Executed Rule'])):
                (executedDecision, decisionTable,ruleId) = newData['Executed Rule'][j]
                message += '<tr><td style="border:2px solid">{}</td>'.format(executedDecision)
                message += '<td style="border:2px solid">{}</td>'.format(decisionTable)
                message += '<td style="border:2px solid">{}</td></tr>'.format(ruleId)
                message += '<tr>'
        else:
            (executedDecision, decisionTable,ruleId) = newData['Executed Rule']
            message += '<tr><td style="border:2px solid">{}</td>'.format(executedDecision)
            message += '<td style="border:2px solid">{}</td>'.format(decisionTable)
            message += '<td style="border:2px solid">{}</td></tr>'.format(ruleId)
            message += '<tr>'
        message += '</table>'
        message += '<p style="text-align:center"><b><a href="{}">{}</a></b></p></body></html>'.format(url_for('show_decision_service', decisionServiceName=decisionServiceName), ('Return to Decision Service ' + decisionServiceName).replace(' ','&nbsp;'))
        message += '<p style="text-align:center"><b><a href="/">{}</a></b></p></body></html>'.format('Return to Decision Central')
        return Response(response=message, status=200)

if __name__ == '__main__':
    app.run(host="0.0.0.0")
