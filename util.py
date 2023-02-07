import base64
from algosdk.v2client import algod
from time import sleep, time


# Helper function to compile program source to base64 encoding
def compile_program(client, source_code):
    compile_response = client.compile(source_code)
    return base64.b64decode(compile_response["result"])


# Helper function to compile program source
def compile_program_b64(client, source_code):
    compile_response = client.compile(source_code)
    return compile_response["result"]


# helper function that formats global state for printing
def format_state(state):
    formatted = {}
    for item in state:
        key = item["key"]
        value = item["value"]
        formatted_key = base64.b64decode(key).decode("utf-8")
        if value["type"] == 1:
            # byte string
            formatted_value = base64.b64decode(value["bytes"])
            formatted[formatted_key] = formatted_value
        else:
            # integer
            formatted[formatted_key] = value["uint"]
    return formatted


# helper function to read app global state
def read_global_state(client, app_id):
    app = client.application_info(app_id)
    global_state = (
        app["params"]["global-state"] if "global-state" in app["params"] else []
    )
    return format_state(global_state)

# helper function to read app local state for account
def read_local_state(client, address, app_id):
    app = client.account_application_info(address, app_id)
    local_state = (
        app["app-local-state"]["key-value"] if "key-value" in app["app-local-state"] else []
    )
    return format_state(local_state)


# Function waits until a block with specific round has been accepted
def waitUntilRound(
        client: algod.AlgodClient,
        round: int,
):
    print("Waiting for round {} ...".format(round))
    currentRound = client.status().get('last-round')
    while not currentRound >= round:
        currentRound = client.status().get('last-round')
        sleep(1)

# Function logs transaction to a default file (for simplicity)
def log_gtx(gtx):
    FILE_PATH = "gtxs.log"
    f = open(FILE_PATH, "a")
    d = [txn.txn.dictify() for txn in gtx]
    f.write("\n" + str(int(time())) + ": " + str(d))
    f.close()
