# DecisionCentralAzure
An Azure compatible, flask implementation of <a href="https://github.com/russellmcdonell/DecisionCentral">DecisionCentral</a>

DecisionCentral is a central repository for all DMN based decision services.  

DecisionCentral  
* Lets you upload DMN compliant Excel workbooks
* Each uplaoded DMN compliant Excell workbook will
  - create a decision service from that DMN compliant workbook
  - create a user interface so that you can enter values and check specific use cases for this decision service
  - creates an API for this decision service which accepts JSON data (the input values) and returns a JSON structure (representing the decision) from this decision service, based upon that data input data.
  - creates web pages detailing all the parts of your decision service
    - The glossary of data items, both inputs and outputs, associated with this decision service
    - The decision sequence (the sequence in which you decision tables will be run)
    - The decision tables that form this decision service
  - creates an OpenAPI specification for the the API associated with this decision service
    - It will be displayed as a web page, but it can also be downloaded and imported to Postman/Swagger etc.

This version allows you to stand up a version of DecisionCentral in Azure.

The process should be
  - Clone this repository
  - Deploy to your Azure App Service ( use Azure add-ins for Visual Studio Code )

If that process doesn't work for you, but you find another one that does, then please let me know ( russell.mcdonell@c-cost.com )

DecisionCentral is not, of itself, a production product. You use pyDMNrules to build those.  
It is intended for use at Hackathons and Connectathons; anywhere you need a complex decision service created quickly and easily.
