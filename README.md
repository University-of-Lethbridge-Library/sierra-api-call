# sierra-api-call
A python script to update holdings information by querying a Library's Sierra API.
The script is configured for three types of queries; updated records for Summon, deleted records for Summon, and updated records for Syndetics.
When run with Python, the script will attempt to authenticate via the Sierra API, query the API for holdings changes, generate marc files for 
updated and/or deleted records, and upload those files to the appropriate FTP server(s).

## Requirements
*  Using Sierra as your ILS
*  Access to a Windows computer or server to run the script from (though it could be modified for Linux or Mac fairly easily)

## Installation
1.  Download and install [Python](https://www.python.org/downloads/) (version 3.3 or later should do the trick).
2.  Click "Clone or download" and then "Download ZIP" on this page.
3.  Unzip the contents to the location that you would like the script to live (this can be anywhere that you have write privileges).
4.  Create a Client Key for the Sierra API. This will be needed in the next step.
See this link for more information: https://csdirect.iii.com/sierrahelp/Content/sadmin/sadmin_other_webapps_api.html
5.  Customize the main config file for your institution.
    1.  Open the `config.ini` file in a plain text editor (Notepad on Windows works, but Notepad++ is better because it makes the file easier to read).
    2.  Modify any lines that need to be customized for your institution. These should generally be preceded by a comment saying \*CHANGEME\*.
    3.  When changing the encoded_credentials line, see this document for instructions: https://techdocs.iii.com/sierraapi/Content/zTutorials/tutAuthenticate.htm
    4.  Save and close the file.
6.  Customize the last_updated config file.
    1.  Open the `last_updated.ini` file in a plain text editor.
    2.  Set the dates in the file. The script will create marc files for every record updated or deleted after (not including) these dates.
    3.  Save and close the file.
7.  Run the script!
    1.  Open a command prompt and navigate to the location of the script.
    2.  Type `python sierra_api_call.py query_type` where `query_type` is replaced with one of the following options:
       *  summon-deleted
       *  summon-updated
       *  syndetics
       *  all
8.  (Optional) Set up a scheduled task to run the script regularly. Our Library closes at or before 11pm, so I set mine to run at 11:15pm.
If you run yours earlier in the day (before closing), you might need to modify the script. Since the last_updated.ini dates are set to whatever day
that the script last ran successfully, you might want to update the json queries so that they grab changes up to *and including* the last_added dates.
Or just run it before midnight but after the last changes have been made and then you won't have to worry about it :-)

## Files
*  sierra_api_call.py: This is the script that you run
*  config.ini: This is the main configuration file
*  last_updated.ini: This is the configuration file that determines the start dates for each query type
*  temp/: This directory contains all of the temporary marc files which are generated when the script runs. The location can be changed in config.ini
*  sierra_api_call.log: A log file. This file is created when the script is first run.

## Potential Updates
#### Please contact me to request these (or other) enhancements
*  Proper command line support (via argparse)
*  Support for authenticated SMTP
*  Functionality to clean out the old temp files

## Tips
#### Most customizations should be possible by editing the two config files, but there are a few things that you might need to change in the script itself
*  The json queries
   *  These are stored in the updated_titles_json, deleted_titles_json, and syndetics_json variables within sierra_api_call.py
   *  The format is similar to Sierra's JSON, but you have to double up the curly braces ({, }) to make them play nice with Python string formatting
*  Logging level
   *  By default, the logging level is set to INFO (which is fairly verbose), but you can display more or less by changing logging.basicConfig
*  Adding or removing query types
   *  If you change the query types, make sure to updated the dictionary in the query_types variable within sierra_api_call.py
   
### Good luck, I hope this script proves useful for you!
