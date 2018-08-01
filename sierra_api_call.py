import requests
import os
import re
import time
import sys
import ftplib
import smtplib
import datetime
import logging
from configparser import ConfigParser, ExtendedInterpolation
from email.mime.text import MIMEText

""" 
Utilizes the Sierra API to query the ILS. 
"""

# Instantiate a configuration parser and then read the configuration file
# ExtendedInterpolation allows for references to other lines in the file
config = ConfigParser(interpolation=ExtendedInterpolation())
config.read("config.ini")

sierra_config = config["Sierra API"]
path_config = config["Local Paths"]
email_config = config["SMTP"]

# Generate an authorization header using credentials from the config file
auth_headers = {"Authorization": "Basic {}".format(sierra_config["encoded_credentials"])}

# Log configuration
# log_location = "C:\code\Summon_Cat_Updates\log\sierra.log"
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(path_config["log_location"]),
        logging.StreamHandler()
    ])

# Maximum number of records to return in one GET request
# There is a limit on the length of URLs, so if you get an error about the 
# URLs being too long, try lowering this 
id_split_length = 30

# The amount of time to wait after a failed API call before trying again
# Lowering this below 300 can cause problems
api_retry_time = 300

# String containing today's date in the format yyyy-mm-dd
today = datetime.date.today().isoformat()

# json query to return all titles updated after a given date
updated_titles_json = '''
{{
  "queries": [
    {{
      "target": {{
        "record": {{
          "type": "bib"
        }},
        "id": 31
      }},
      "expr": {{
        "op": "equals",
        "operands": [
          "-",
          ""
        ]
      }}
    }},
    "and",
    {{
      "target": {{
        "record": {{
          "type": "bib"
        }},
        "id": 84
      }},
      "expr": {{
        "op": "greater_than",
        "operands": ["{date}"]
      }}
    }}
  ]
}}
'''

# json query to return all titles deleted after a given date
deleted_titles_json = '''
{{
  "queries": [
    {{
      "target": {{
        "record": {{
          "type": "bib"
        }},
        "id": 31
      }},
      "expr": {{
        "op": "not_equal",
        "operands": [
          "-",
          ""
        ]
      }}
    }},
    "and",
    {{
      "target": {{
        "record": {{
          "type": "bib"
        }},
        "id": 84
      }},
      "expr": {{
        "op": "greater_than",
        "operands": ["{date}"]
      }}
    }}
  ]
}}
'''

syndetics_json = '''
{{
  "queries": [
    {{
      "target": {{
        "record": {{
          "type": "bib"
        }},
        "id": 84
      }},
      "expr": {{
        "op": "greater_than",
        "operands": ["{date}"]
      }}
    }},
    "and",
    {{
      "target": {{
        "record": {{
          "type": "bib"
        }},
        "id": 31
      }},
      "expr": {{
        "op": "equals",
        "operands": [
          "-",
          ""
        ]
      }}
    }},
    "and",
    {{
      "target": {{
        "record": {{
          "type": "bib"
        }},
        "id": 28
      }},
      "expr": {{
        "op": "not_equal",
        "operands": [
          "      ",
          ""
        ]
      }}
    }},
    "and",
    {{
      "target": {{
        "record": {{
          "type": "bib"
        }},
        "id": 26
      }},
      "expr": {{
        "op": "not_equal",
        "operands": [
          "ulgmc",
          ""
        ]
      }}
    }}
  ]
}}
'''


def get_bearer_token():
    # Make the authentication call and return a dict with the bearer token
    auth_response = requests.post(sierra_config["auth_url"], headers=auth_headers)
    bearer_token = auth_response.json()['access_token']

    # Display the results of the authentication call
    if auth_response.status_code == requests.codes.ok:
        logging.info("Authorization successful.")
        logging.debug("Bearer token: {}".format(bearer_token))
    else:
        logging.critical("Bearer authorization failed. Check the value of encoded_credentials in config.ini. Error code: {}".format(auth_response.status_code))
        quit()
    
    return {"Authorization": "Bearer {}".format(bearer_token)}


def generate_id_list(json_query, headers):
    """ Creates a comma delimited string of bib record ids """
    # Perform a POST request to get bib records modified/deleted after query_date
    titles_response = requests.post(sierra_config["bibs_post_url"], data=json_query, headers=headers)
    logging.info("POST request successful. Number of titles returned: {}".format(titles_response.json()["total"]))

    # Create a comma delimited list of ids from the POST query results
    bib_list = ""
    for entry in titles_response.json()["entries"]:
        bib_list += entry["link"].split('/')[-1] + ","
    if bib_list == "":
        return None
    else:
        return bib_list[0:-1]  # Removes trailing comma


def download_file(url, headers, filename):
    """ Function to download a file given the url and an authentication header """
    local_filename = os.path.join(path_config["output_location"], filename)
    r = requests.get(url, headers=headers, stream=True)
    with open(local_filename, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024): 
            if chunk:  # filter out keep-alive new chunks
                f.write(chunk)
    return local_filename

def get_last_updated_date(query_type):
    # Determine the date that the given query_type was last updated
    # Return the date and the last_updated config file 
    chosen_date = None
    # Determine the date to be used in the query
    last_updated_config = ConfigParser()
    if os.path.exists(path_config["last_updated_location"]):
        # Create a new config object for the last updated location file
        try:
            # Open the file that indicates when this script was last ran
            last_updated_config.read(path_config["last_updated_location"])
        except:
            logging.critical("Could not read last updated file")
            raise
        try:
            chosen_date = last_updated_config["Last Updated"][query_type.short_name]
        except:
            logging.critical("The date provided in the last updated file is invalid. Please correct the date and try again")
            raise
    else:  # If the date isn't given via command line or file, display an error
        logging.critical("Last updated file not found. Please ensure that the last_updated_location in the config file is pointing to a valid file")
        quit()
    validate_date(chosen_date)
    return (chosen_date, last_updated_config)


def initiate_api_call(query_type):
    # Performs validation, begins the API call for the chosen
    # query type (Summon updates, Summon deletions, or Syndetics),
    # updates the last_added file, and returns a string describing the results
    # Perform a GET request to generate a marc file of bib records with
    # the syndetics query
    headers = get_bearer_token()
    chosen_date, last_updated_config = get_last_updated_date(query_type)
    ids = generate_id_list(query_type.json.format(date=chosen_date), headers)

    if ids:
        # Makes sure that a list was returned rather than None
        number_ids = len(ids.split(","))
    else:
        # This indicates that None was returned
        number_ids = 0

    if number_ids > 0:
        logging.info("Generating marc file for {}".format(query_type.full_name))
        final_filename = query_type.short_name + "-" + chosen_date + ".mrc"
        final_path = os.path.join(path_config["output_location"], final_filename)
        prepare_id_list(ids, final_filename, chosen_date, headers)
        logging.info("Finished generating marc file for {}. Location: {}".format(query_type.full_name,final_path))

        # Upload the marc file to the appropriate FTP server
        ftp_upload(config[query_type.ftp_config_string], final_path, query_type.ftp_directory + final_filename)

    # Update the file showing when the script was last run
    with open(path_config["last_updated_location"], 'w') as last_updated_file:
        last_updated_config["Last Updated"][query_type.short_name] = today
        last_updated_config.write(last_updated_file)
    # Return the results as a formatted string
    return "{}\nRecords: {}\nDate Range: {}\n\n".format(query_type.full_name, str(number_ids), chosen_date + " - " + today)


def prepare_id_list(id_list, filename, chosen_date, headers):
    """ Perform a GET request and download the resulting marc file """
    # Split the list of ids into smaller segments since the API can't handle
    # get requests with URLS over a certain length
    split_ids = id_list.split(",")
    num_chunks = 0
    if len(split_ids) > id_split_length:  # list is too large, need to split
        outfile = open(os.path.join(path_config["output_location"], filename), 'w')
        for chunk in chunks(split_ids, id_split_length):
            temp_filename = "temp-" + chosen_date + "-pt" + str(num_chunks) + ".mrc"
            api_call_successful = False
            while not api_call_successful:
                api_call_results = get_marc_api_call(",".join(chunk), temp_filename, headers)  # Create temp file
                api_call_successful = api_call_results[0]
                headers = api_call_results[1]

            with open(os.path.join(path_config["output_location"], temp_filename)) as infile:
                outfile.write(infile.read())
            os.remove(os.path.join(path_config["output_location"], temp_filename))
            #paths.append(os.path.join(output_location, temp_filename))
            num_chunks += 1

    else: #list is small enough that there is no need to split it
        get_marc_api_call(id_list, filename, headers)


def get_marc_api_call(id_list, filename, headers):
    """ Perform a GET request and download the resulting marc file 
    Returns a list where the first item is a boolean indicating success or 
    failure of the marc file download, and the second are the headers (since
    multiple failures will cause the function to try to re-authenticate)
    """
    params = {"limit": "99999999", "id":id_list}
    marc_response = requests.get(sierra_config["bibs_get_url"], params=params, headers=headers)

    #Download the marc file for deleted records
    try:
        download_file(marc_response.json()["file"], headers, filename)
        return [True, headers]
    except:
        if marc_response.json()["code"] == 138:
            logging.warning("Too many requests. Waiting to try again. This will take at least five minutes")
            time.sleep(api_retry_time)
        else:
            logging.debug(marc_response.text)
            # Authentication has likely timed out, so try to re-authenticate
            logging.warning("Reauthenticating")
            new_headers = get_bearer_token()
            return [False, new_headers]
        return [False, headers]


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


def ftp_upload(ftp_config, file_path, ftp_path):
    """Upload a file given by file_path to an ftp location given by ftp_path
    ftp_config is a config parser object
    """
    session = ftplib.FTP(ftp_config["ftp_host"], ftp_config["ftp_user"], ftp_config["ftp_pass"])
    file = open(file_path,'rb')                 
    session.storbinary('STOR {}'.format(ftp_path), file)     
    file.close()                                    
    session.quit()


def send_email(server, port, subject, message, sender, recipients):
    server = smtplib.SMTP(server, port)
    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipients
    server.sendmail(sender, recipients.split(","), msg.as_string())


def validate_date(date):
    # Date should be in the format yyyy-mm-dd
    # Note: this isn't smart enough to check for weird input like 2018-09-36
    if not re.match("[0-2]\d{3}-[0-1]?\d-[0-3]?\d", date):
        logging.critical("Invalid date format. Please restart this script and try again.")
        quit()
    else:
        logging.info("Using date: {}".format(date))


class QueryType:
    def __init__(self, short_name, full_name, json, ftp_config_string, ftp_directory = ""):
        self.short_name = short_name
        self.full_name = full_name
        self.json = json
        self.ftp_config_string = ftp_config_string
        self.ftp_directory = ftp_directory

# Dictionary of different query types
query_types = {
        "summon-deleted": QueryType("summon-deleted", "Summon Deleted", deleted_titles_json, "Summon FTP", "deletes/"),
        "summon-updated": QueryType("summon-updated", "Summon Updated", updated_titles_json, "Summon FTP", "updates/"),
        "syndetics": QueryType("syndetics", "Syndetics", syndetics_json, "Syndetics FTP"),
        }

# ==Main code execution starts here==
if __name__ == "__main__":
    results = ""
    # Determine which type of query to run
    argument = ""
    if len(sys.argv) > 1:  # Get the type from the command line
        argument = sys.argv[1].lower()
    else:
        logging.critical("Please specify the type of query as the first argument after the name of the script")
        logging.critical("Valid query types are: " + ", ".join(name for name, query_type in query_types.items()))
        quit()

    if argument == "all":
        for name, query_type in query_types.items():
            results += initiate_api_call(query_type)

    elif argument in query_types:
        results += initiate_api_call(query_types[argument])

    else:
        logging.critical("Invalid query type")
        logging.critical("Valid query types are: " + ", ".join(name for name, query_type in query_types.items()))
        quit()

    # Log the results
    logging.info("==== RESULTS ====")
    logging.info(results)

    # Send an email indicating that the script completed successfully
    if email_config and email_config["smtp_server"] and email_config["smtp_port"] and email_config["email_sender"] and email_config["email_recipients"]:
        send_email(email_config["smtp_server"], email_config["smtp_port"], "Sierra holdings update successful", results, email_config["email_sender"], email_config["email_recipients"])
        logging.info("All done! Results email sent successfully")
    else:
        logging.info("All done! If you would like an email with the results to be sent in the future, please configure the SMTP settings in config.ini")

