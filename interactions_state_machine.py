# -----------------           Description          -----------------
# This script provides a state machine for interaction with Compound smart Contract through the Algorand SDK.

# -----------------           Imports          -----------------
import base64
import glob
from algosdk.v2client import algod
from algosdk import account, mnemonic, error, transaction
from algosdk.abi import Contract
from algosdk import encoding
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, AccountTransactionSigner, \
    TransactionWithSigner
from algosdk.logic import get_application_address
from demo.interact_w_CompoundContract import *
from demo.interact_w_FarmCompoundContract import *
from util import *

import src.config as cfg

# -----------------       Global variables      -----------------
# Nodes
algod_client = None

# User secret key - FOR TEST PURPOSES ONLY!
user_sk = None
# User address
user_address = None
# Short form for user address
user_address_short = None

# ID of created compound contract
cc_id = 0

# Staking contract ID (i.e. of the staking pool which you would like to be compounding)
sc_id = 0
# ID of associated contract to the staking contract
ac_id = 0

# ID of AMM contract for swapping reward asset back to stake asset
amm_id = 0

# Address of the pool of AMM for swapping
p_addr = ""

# ID of staking asset
s_asa_id = 0
# ID of reward asset
r_asa_id = 0

# Contract type of the compounding - i.e. normal for staking pool (CC_TYPE) or for farming pool (FC_TYPE)
CC_TYPE = 0
FC_TYPE = 1
contract_type = CC_TYPE


# State (unique) encoding
S_INIT = 0
S_CHOOSE_USER = 1
S_TOP_MENU = 2
S_DEPLOY = 3
S_CONNECT = 4
S_CREATOR = 5
S_SETUP = 6
S_DELETE = 7
S_BOXES = 8
S_USER = 9
S_OPTIN = 10
S_OPTOUT = 11
S_FORCE_CLOSE = 12
S_STAKE = 13
S_WITHDRAW = 14
S_COMPOUND = 15
S_ACCUMULATE = 16
S_COMPOUND_NOW = 17
S_SCHEDULE_COMPOUND = 18
S_READ_BOXES = 19

# Current state
cs = -1
# Next state
ns = -1
# Previous state
ps = -1

# ---------------------------------------------------------------

# -----------------          Functions          -----------------


def init():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    print("Welcome to interface for interacting with autocompounding contracts!")

# # ---- FOR TEST PURPOSES ONLY ----
#     # Algod connection parameters. Node must have EnableDeveloperAPI set to true in its config
#     algod_address = "http://localhost:4001"  # "https://node.testnet.algoexplorerapi.io"  #
#     algod_token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
#     # Initialize an algodClient
#     algod_client = algod.AlgodClient(algod_token, algod_address)

# # ---- ---- ---- ---- ---- ---- ----

    while True:
        algod_address = input("First please input address to algod node to connect to: ")
        algod_token = input("Enter algod token: ")

        # Initialize an algodClient
        algod_client = algod.AlgodClient(algod_token, algod_address)

        try:
            algod_client.health()
            break
        except error.AlgodHTTPError as e:
            print("\tError: " + str(e))
            print("\tPlease try connecting to a different node")


    ns = S_CHOOSE_USER

    cfg.init_global_vars(algod_client)


def choose_user():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    while True:
        path_to_m = input("Please enter path to .txt file with your wallet's mnemonic. " + \
                          "(THIS IS FOR TEST PURPOSES ONLY!): ")

        try:
            with open(path_to_m, 'r') as f:
                user_mnemonic = f.read()
                user_sk = mnemonic.to_private_key(user_mnemonic)
                user_address = account.address_from_private_key(user_sk)
                user_address_short = str(user_address[0:4]) + "..." + str(user_address[-4:])
                print("Welcome user: " + user_address_short)
            break
        except Exception:
            print("You did not enter a path to a .txt file with mnemonic!")
            continue


    ns = S_TOP_MENU


def top_menu():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")

    print("Your options are:")
    print("\t1) Switch user")
    print("\t2) Deploy new compounding contract")
    print("\t3) Connect to existing compounding contract")
    print("\t4) Exit")

    while True:
        c = input("Please enter number of the option you would like to choose: ")
        try:
            c = int(c)
        except ValueError:
            print("You did not enter a valid number!")
            continue

        if c == 1:
            ns = S_CHOOSE_USER
            return
        elif c == 2:
            ns = S_DEPLOY
            return
        elif c == 3:
            ns = S_CONNECT
            return
        elif c == 4:
            exit(1)
        else:
            print("You did not enter a valid number!")
            continue

def deploy_new_CC():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    while True:
        print("Please choose what is the type of the compounding contract you want to create:")
        print("\t{}) Compounding for staking pool".format(CC_TYPE))
        print("\t{}) Compounding for farming pool".format(FC_TYPE))

        contract_type = input("Please enter number of the option you would like to choose: ")
        try:
            contract_type = int(contract_type)
        except ValueError:
            print("You did not enter a valid number!")
            continue
        if contract_type == CC_TYPE or contract_type == FC_TYPE:
            break
        else:
            print("You did not enter a valid number!")
            continue

    while True:
        print("Please enter the following parameters of the compounding contract you want to create:")

        sc_id = input("App ID of Cometa staking contract to compound: ")
        try:
            sc_id = int(sc_id)
        except ValueError:
            print("You did not enter a valid number!")
            continue
        try:
            algod_client.application_info(sc_id)
        except error.AlgodHTTPError as e:
            print("\tError: " + str(e))
            continue

        ac_id = input("App ID of Cometa staking contract's associated contract: ")
        try:
            ac_id = int(ac_id)
        except ValueError:
            print("You did not enter a valid number!")
            continue
        try:
            algod_client.application_info(ac_id)
        except error.AlgodHTTPError as e:
            print("\tError: " + str(e))
            continue

        if contract_type == FC_TYPE:
            amm_id = input("App ID of AMM contract: ")
            try:
                amm_id = int(amm_id)
                algod_client.application_info(amm_id)
            except ValueError:
                print("You did not enter a valid number!")
                continue
            except error.AlgodHTTPError as e:
                print("\tError: " + str(e))
                continue

            # Future improvement, find automatically the address
            p_addr = input("Pool address belonging to AMM contract and staking asset: ")
            try:
                algod_client.account_info(p_addr)
            except error.AlgodHTTPError as e:
                print("\tError: " + str(e))
                continue

            mraal = input("Minimum amount of rewards received before they are added to the farming pool [base unit]: ")
            try:
                mraal = int(mraal)
            except ValueError:
                print("You did not enter a valid number!")
                continue

        cp = input("Claim period - number of rounds after pool ends that claiming can be done: ")
        try:
            cp = int(cp)
            if cp <= 0:
                raise ValueError
        except ValueError:
            print("You did not enter a valid number!")
            continue

        try:
            print("")
            if contract_type == FC_TYPE:
                [cc_id, s_asa_id, r_asa_id] = createFarmCompoundContract(algod_client, user_sk, sc_id, ac_id, p_addr,
                                                                         amm_id, cp, mraal)
            else:
                [cc_id, s_asa_id] = createCompoundContract(algod_client, user_sk, sc_id, ac_id, cp)
            print("\nCreated compound contract with app ID: " + str(cc_id))
            print("For asset with ID: " + str(s_asa_id))
            break
        except Exception as e:
            print("\tError: " + str(e))
            continue

    ns = S_CREATOR

def connect_to_CC():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    while True:
        cc_id = input("Please enter the app ID of the compound contract you are trying to connect to: ")
        try:
            cc_id = int(cc_id)

            cc_state = read_global_state(algod_client, cc_id)
            sc_id = cc_state["SC_ID"]
            ac_id = cc_state["AC_ID"]
            s_asa_id = cc_state["S_ASA_ID"]

            if "AMM_ID" not in cc_state:
                contract_type = CC_TYPE
            else:
                contract_type = FC_TYPE
                r_asa_id = cc_state["R_ASA_ID"]
                amm_id = cc_state["AMM_ID"]
                p_addr = encoding.encode_address(cc_state["P_ADDR"])

        except ValueError:
            print("You did not enter a valid number!")
            continue
        except KeyError:
            print("Are you really conneting to a compounding contract?")
            continue
        except error.AlgodHTTPError as e:
            print("\tError: " + str(e))
            continue

        try:
            cc_creator_address = algod_client.application_info(cc_id)["params"]["creator"]
        except error.AlgodHTTPError as e:
            print("\tError: " + str(e))
            ns = ps
            return

        if cc_creator_address == user_address:
            ns = S_CREATOR
            print("Welcome " + user_address_short + ", compound contract creator!")
            return
        else:
            print("Welcome " + user_address_short + "!")
            ns = S_USER
            return


def creator_interact():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    print("You are managing contract with ID " + str(cc_id) + " and following parameters:")
    try:
        cc_state = read_global_state(algod_client, cc_id)
        print("\tConnected to staking contract ID: {}".format(cc_state["SC_ID"]))
        print("\tConnected to associated contract ID: {}".format(cc_state["AC_ID"]))
        print("\tStaking ASA ID: {}".format(cc_state["S_ASA_ID"]))

        if contract_type == FC_TYPE:
            print("\tReward ASA ID: {}".format(cc_state["R_ASA_ID"]))
            print("\tConnected AMM contract ID: {}".format(cc_state["AMM_ID"]))
            print("\tConnected AMM pool address: {}".format(encoding.encode_address(cc_state["P_ADDR"])))
            print("\tMinimum amount of reward ASA ID before they are added to the farming pool: {} [base unit]".format(
                cc_state["MRAAL"]))

        print("\tTotal stake: {} [base unit]".format(cc_state["TS"]))
        print("\tPool start round: {} [round]".format(cc_state["PSR"]))
        print("\tPool end round: {} [round]".format(cc_state["PER"]))
        print("\tClaiming period: {} [rounds]".format(cc_state["CP"]))
        print("\tLast compound done: {}".format(cc_state["LCD"]))
        print("\tLast compound round: {} [round]".format(cc_state["LCR"]))
        print("\tNumber of stakers: {}".format(cc_state["NS"]))
        print("\tNumber of boxes: {}".format(cc_state["NB"]))

    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
        ns = S_TOP_MENU
        return
    except KeyError:
        print("Wrong contract!")
        ns = S_TOP_MENU
        return

    print("\nYour options are:")
    print("\t1) Setup contract")
    print("\t2) Delete contract")
    print("\t3) Delete contract boxes")
    print("\t4) Interact as user")
    print("\t5) Read all compounding increments")
    print("\t6) Go to the top menu")

    while True:
        c = input("Please enter number of the option you would like to choose: ")
        try:
            c = int(c)
        except ValueError:
            print("You did not enter a valid number!")
            continue

        if c == 1:
            ns = S_SETUP
            return
        elif c == 2:
            ns = S_DELETE
            return
        elif c == 3:
            ns = S_BOXES
            return
        elif c == 4:
            ns = S_USER
            return
        elif c == 5:
            ns = S_READ_BOXES
            return
        elif c == 6:
            ns = S_TOP_MENU
            return
        else:
            print("You did not enter a valid number!")
            continue


def setup_CC():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        if contract_type == FC_TYPE:
            setupFarmCompoundContract(algod_client, user_sk, cc_id, sc_id, s_asa_id, r_asa_id)
        else:
            setupCompoundContract(algod_client, user_sk, cc_id, sc_id, s_asa_id)
        print("\nSuccessfully setup contract with app ID: " + str(cc_id))
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_CREATOR


def delete_CC():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        if contract_type == FC_TYPE:
            deleteFarmCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id, r_asa_id)
        else:
            deleteCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id)
        print("\nSuccessfully deleted contract with app ID: " + str(cc_id))
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_CREATOR


def delete_boxes():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        deleteAllBoxes(algod_client, user_sk, cc_id)
        print("\nSuccessfully deleted all boxes of app ID: " + str(cc_id))
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_CREATOR


def user_interact():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    print("You are interacting with contract with ID " + str(cc_id) + " and following parameters:")

    try:
        cc_state = read_global_state(algod_client, cc_id)
        print("\tConnected to staking contract ID: {}".format(cc_state["SC_ID"]))
        print("\tConnected to associated contract ID: {}".format(cc_state["AC_ID"]))
        print("\tStaking ASA ID: {}".format(cc_state["S_ASA_ID"]))

        if contract_type == FC_TYPE:
            print("\tReward ASA ID: {}".format(cc_state["R_ASA_ID"]))
            print("\tConnected AMM contract ID: {}".format(cc_state["AMM_ID"]))
            print("\tConnected AMM pool address: {}".format(encoding.encode_address(cc_state["P_ADDR"])))
            print("\tMinimum amount of reward ASA ID before they are added to the farming pool: {} [base unit]".format(
                cc_state["MRAAL"]))

        print("\tTotal stake: {} [base unit]".format(cc_state["TS"]))
        print("\tPool start round: {} [round]".format(cc_state["PSR"]))
        print("\tPool end round: {} [round]".format(cc_state["PER"]))
        print("\tClaiming period: {} [rounds]".format(cc_state["CP"]))
        print("\tLast compound done: {}".format(cc_state["LCD"]))
        print("\tLast compound round: {} [round]".format(cc_state["LCR"]))
        print("\tNumber of stakers: {}".format(cc_state["NS"]))
        print("\tNumber of boxes: {}".format(cc_state["NB"]))

        if contract_type == FC_TYPE:
            next_trig_round = getFarmTriggerRound(algod_client, cc_id)
        else:
            next_trig_round = getTriggerRound(algod_client, cc_id)
        if next_trig_round == 0:
            print("\n\tCompounding can be triggered!")
        elif next_trig_round > 0:
            print("\n\tNext scheduled compounding can be trigger at round: " + str(next_trig_round))
        elif next_trig_round == -1:
            print("\n\tPool has already ended. Please withdraw your stake.")

    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
        ns = S_TOP_MENU
        return
    except KeyError:
        print("Wrong contract!")
        ns = S_TOP_MENU
        return
    print("")

    opted_in_already = True
    try:
        cc_local_state = read_local_state(algod_client, user_address, cc_id)
    except KeyError:
        opted_in_already = False
        print("\tIf you are a new user, please opt in!")
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
        opted_in_already = False
        print("\tIf you are a new user, please opt in!")

    if opted_in_already:
        your_stake = getUsersCompoundStake(algod_client, user_address, cc_id)
        print("\nYou have {} [base unit] of ASA ID '{}' in the contract".format(
            your_stake, s_asa_id))
        NB_diff = cc_state["NB"] - cc_local_state["LNB"]
        if NB_diff > 0:
            print("\t**For advance users:** You have {} results to claim".format(NB_diff))

    try:
        ai = algod_client.account_asset_info(user_address, s_asa_id)
        print("\nYou are holding {} [base unit] of staking asset".format(ai['asset-holding']['amount']))
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
        print("\tAre you opted-in the staking asset?")

    print("\nYour options are:")
    print("For basic users:")
    if not(opted_in_already):
        print("\t0) Opt-in to contract")
    print("\t1) Stake")
    print("\t2) Withdraw")
    print("\t3) Opt-out of contract")
    print("For advance users:")
    print("\t4) Trigger compounding")
    print("\t5) Compound now - even if not scheduled")
    print("\t6) Schedule additional optimal compounding")
    print("\t7) Locally accumulate")
    print("\t8) Clear your contract state")
    print("\t9) Read all compounding increments")
    print("\t10) Go to the top menu")

    while True:

        c = input("Please enter number of the option you would like to choose: ")
        try:
            c = int(c)
        except ValueError:
            print("You did not enter a valid number!")
            continue

        if c == 0:
            ns = S_OPTIN
            return
        elif c == 1:
            ns = S_STAKE
            return
        elif c == 2:
            ns = S_WITHDRAW
            return
        elif c == 3:
            ns = S_OPTOUT
            return
        elif c == 4:
            ns = S_COMPOUND
            return
        elif c == 5:
            ns = S_COMPOUND_NOW
            return
        elif c == 6:
            ns = S_SCHEDULE_COMPOUND
            return
        elif c == 7:
            ns = S_ACCUMULATE
            return
        elif c == 8:
            ns = S_FORCE_CLOSE
            return
        elif c == 9:
            ns = S_READ_BOXES
            return
        elif c == 10:
            ns = S_TOP_MENU
            return
        else:
            print("You did not enter a valid number!")
            continue


def optin_to_CC():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        optinCompoundContract(algod_client, user_sk, cc_id)
        print("\nSuccessfully opted into app ID: " + str(cc_id))
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\tAre you opted into the contract?")
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_USER


def optout_of_CC():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        optoutCompoundContract(algod_client, user_sk, cc_id)
        print("\nSuccessfully opted out of app ID: " + str(cc_id))
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\tAre you opted into the contract?")
    except Exception as e:
        print("\tError: " + str(e))
        print("\tHave you withdrawn you full amount?")

    ns = S_USER


def force_opt_out_of_CC():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        clearStateCompoundContract(algod_client, user_sk, cc_id)
        print("\nSuccessfully forcefully opted out of app ID: " + str(cc_id))
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\tAre you opted into the contract?")
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_USER


def stake_to_CC():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    while True:
        amt = input("Please enter the amount [base unit] you would like to deposit to the compound contract: ")
        try:
            amt = int(amt)
            break
        except ValueError:
            print("You did not enter a valid number!")
            continue

    try:
        if contract_type == FC_TYPE:
            stakeFarmCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id, r_asa_id, p_addr, amm_id, amt)
        else:
            stakeCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id, amt)
        print("\nSuccessfully staked {} to app ID: {}".format(amt, str(cc_id)))
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\tAre you opted into the contract?")
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_USER


def withdraw_from_CC():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    while True:
        amt = input("Please enter the amount [base unit] you would like to withdraw from the compound contract: ")
        try:
            amt = int(amt)
            break
        except ValueError:
            print("You did not enter a valid number!")
            continue

    try:
        if contract_type == FC_TYPE:
            amt = withdrawFarmCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id, r_asa_id, p_addr,
                                               amm_id, amt)
        else:
            amt = withdrawCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id, amt)
        print("\nSuccessfully withdrawn " + str(amt))
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\tAre you opted into the contract?")
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_USER


def trigger_compounding():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        if contract_type == FC_TYPE:
            tmp = triggerFarmCompoundingCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id, r_asa_id,
                                                         p_addr, amm_id)
        else:
            tmp = triggerCompoundingCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id)

        if tmp == 1:
            print("\nSuccessfully compounded stake!")
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\tAre you opted into the contract?")
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_USER


def locally_accumulate():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        localClaimCompoundContract(algod_client, user_sk, cc_id)
        print("\nSuccessfully locally claimed the stake. You can now withdraw it!")
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\tAre you opted into the contract?")
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_USER


def compound_now():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        if contract_type == FC_TYPE:
            compoundNowFarmCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id, r_asa_id, p_addr,
                                            amm_id)
        else:
            compoundNowCompoundContract(algod_client, user_sk, cc_id, sc_id, ac_id, s_asa_id)
        print("\nSuccessfully compounded the stake!")
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\tAre you opted into the contract?")
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_USER


def schedule_optimal_compound():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        sheduleAdditionalCompounding(algod_client, user_sk, cc_id)
        print("\nSuccessfully scheduled an optimal additional compounding!")
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\tAre you opted into the contract?")
    except Exception as e:
        print("\tError: " + str(e))

    ns = S_USER


def read_all_boxes():
    global cs, ns, ps, cc_id, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    print("\n----------------------------------------------------------------------------------------")
    try:
        readAllCompoundingContributions(algod_client, cc_id)
    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except Exception as e:
        print("\tError: " + str(e))

    ns = ps


# ---------------------------------------------------------------


def main():
    global cs, ns, ps, sc_id, ac_id, contract_type, amm_id, p_addr, s_asa_id, r_asa_id, user_sk, user_address, user_address_short, algod_client

    cs = S_INIT

    while True:

        if cs == S_INIT:
            init()
        elif cs == S_CHOOSE_USER:
            choose_user()
        elif cs == S_TOP_MENU:
            top_menu()
        elif cs == S_DEPLOY:
            deploy_new_CC()
        elif cs == S_CONNECT:
            connect_to_CC()
        elif cs == S_CREATOR:
            creator_interact()
        elif cs == S_SETUP:
            setup_CC()
        elif cs == S_DELETE:
            delete_CC()
        elif cs == S_BOXES:
            delete_boxes()
        elif cs == S_USER:
            user_interact()
        elif cs == S_OPTIN:
            optin_to_CC()
        elif cs == S_OPTOUT:
            optout_of_CC()
        elif cs == S_FORCE_CLOSE:
            force_opt_out_of_CC()
        elif cs == S_STAKE:
            stake_to_CC()
        elif cs == S_WITHDRAW:
            withdraw_from_CC()
        elif cs == S_COMPOUND:
            trigger_compounding()
        elif cs == S_ACCUMULATE:
            locally_accumulate()
        elif cs == S_COMPOUND_NOW:
            compound_now()
        elif cs == S_SCHEDULE_COMPOUND:
            schedule_optimal_compound()
        elif cs == S_READ_BOXES:
            read_all_boxes()
        else:
            raise ValueError('Invalid state')

        ps = cs
        cs = ns


if __name__ == "__main__":
    main()


