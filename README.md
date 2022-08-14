# DecisionCentralAzure
An Azure compatible, flask implementation of <a href="https://github.com/russellmcdonell/DecisionCentral">DecisionCentral</a>

DecisionCentralAzure is a central repository for all DMN based decision services.  

DecisionCentralAzure  
* Creates a web site that lets you upload DMN compliant Excel workbooks or DMN conformant XML files
* For each uploaded DMN compliant Excel workbook or DMN compliant XML file, DecisionCentral will
  - create a decision service from that DMN compliant Excel workbook or DMN conformant XML file
  - create a user interface where users can enter values and check specific use cases for this decision service
  - creates an API for this decision service which accepts JSON data (the input values) and returns a JSON structure (representing the decision)    
* For each decision service, DecisionCentral will create web pages detailing all the parts of your decision service
    - The glossary of data items, both inputs and outputs, associated with this decision service
    - The decision sequence (the sequence in which you decision tables will be run)
    - The decision tables that form this decision service
    - An OpenAPI specification for the the API associated with this decision service which will be displayed as a web page, but it can also be downloaded and imported to Postman/Swagger etc.
* For each decision table, within each decision service, DecisionCentral will
  - create a DMN compliant representation of the rules built when the decision service was created
  - create a user interface where users can enter values and check specific use cases for this decision table within this decision service
  - create an API for this decision table within this decision service which accepts JSON data (the input values) and returns a JSON structure (representing the decision)    
  - createe an OpenAPI specification for the the API associated with this decision table with this decision service which will be displayed as a web page, but it can also be downloaded and imported to Postman/Swagger etc.

DecisionCentralAzure also has an API for uploading a DMN compliant Excel workbook or DMN conformant XML file, plus and API for deleting a decision service.

This version allows you to stand up a version of [DecisionCentral (https://github.com/russellmcdonell/DecisionCentral) in Azure. Being the flask version, it will create a web site and API services on port 5000.

The process should be
  - Clone this repository
  - Deploy to your Azure App Service ( use Azure add-ins for Visual Studio Code )

If that process doesn't work for you, but you find another one that does, then please let me know ( russell.mcdonell@c-cost.com )

DecisionCentralAzure is not, of itself, a production product. You use pyDMNrules to build those.  
It is intended for use at Hackathons and Connectathons; anywhere you need a complex decision service created quickly and easily.
