# -----------------           Imports          -----------------
import base64
import glob
import math
from math import ceil

from algosdk.v2client import algod, indexer
from algosdk import account, mnemonic, error, transaction
from algosdk.abi import Contract
from algosdk import encoding
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, AccountTransactionSigner, \
    TransactionWithSigner
from algosdk.logic import get_application_address

from util import *

import src.config as cfg
from demo.interact_w_CompoundContract import localClaimCompoundContract, getTriggerRound

# ---------------------------------------------------------------


def createFarmCompoundContract(
    algod_client: algod.AlgodClient,
    creatorSK: str,
    sc_id: int,
    ac_id: int,
    p_addr: str,
    amm_id: int,
    cp: int,
    mraal: int
):
    creator_address = account.address_from_private_key(creatorSK)

    # Declare application state storage (immutable)
    global_schema = transaction.StateSchema(cfg.FC_NUM_GLOBAL_UINT, cfg.FC_NUM_GLOBAL_BYTES)
    local_schema = transaction.StateSchema(cfg.FC_NUM_LOCAL_UINT, cfg.FC_NUM_LOCAL_BYTES)

    app_args = [
        sc_id,
        ac_id,
        p_addr,
        amm_id,
        cp,
        mraal
    ]

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(creatorSK)

    # Simple call to the `create_app` method, method_args can be any type but _must_
    # match those in the method signature of the contract
    atc.add_method_call(
        app_id=0,
        method=cfg.FC_contract.get_method_by_name("create_app"),
        sender=creator_address,
        sp=sp,
        signer=signer,
        approval_program=cfg.FC_approval_program,
        clear_program=cfg.FC_clear_state_program,
        local_schema=local_schema,
        global_schema=global_schema,
        method_args=app_args,
        extra_pages=cfg.FC_ExtraProgramPages,
        foreign_assets=None,
        foreign_apps=[sc_id]
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)
    app_id = transaction.wait_for_confirmation(algod_client, result.tx_ids[0])['application-index']

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    assert app_id is not None and app_id > 0

    cc_state = read_global_state(algod_client, app_id)
    s_asa_id = cc_state["S_ASA_ID"]
    r_asa_id = cc_state["R_ASA_ID"]

    return [app_id, s_asa_id, r_asa_id]


def setupFarmCompoundContract(
    algod_client: algod.AlgodClient,
    creatorSK: str,
    fc_id: int,
    sc_id: int,
    s_asa_id: int,
    r_asa_id: int
):
    creator_address = account.address_from_private_key(creatorSK)

    # Get farm compound contract address
    FC_address = get_application_address(fc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(creatorSK)

    sp.flat_fee = True
    # There are 5 txs: fund the contract for opt-ins, call to FC, SC opt-in, S_ASA_ID opt-in and R_ASA_ID opt-in
    sp.fee = 5 * sp.min_fee

    # Fund the compound contract with minimal balance to opt-in to the staking contract and ASA
    # Minimal balance: minimal balance for any account + minimal balance for 2 ASA + for opt-in to staking contract (not
    # exactly sure about the amount since it is in Reach - just one Byte slice? = 25_000 + 25_000; seems to be 3 slices)
    amt = 100_000 + 2*100_000 + 50_000*3

    fund_tx = transaction.PaymentTxn(
        sender=creator_address,
        sp=sp,
        receiver=FC_address,
        amt=amt,
    )
    tws = TransactionWithSigner(fund_tx, signer)

    atc.add_transaction(tws)
    sp.fee = 0

    app_args = []
    # Call to the `on_setup` method
    atc.add_method_call(
        app_id=fc_id,
        method=cfg.FC_contract.get_method_by_name("on_setup"),
        sender=creator_address,
        sp=sp,
        signer=signer,
        method_args=app_args,
        foreign_assets=[s_asa_id, r_asa_id],
        foreign_apps=[sc_id]
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def deleteFarmCompoundContract(algod_client: algod.AlgodClient,
    creatorSK: str,
    fc_id: int,
    sc_id: int,
    ac_id: int,
    s_asa_id: int,
    r_asa_id: int
):
    creator_address = account.address_from_private_key(creatorSK)

    # # Get farm compound contract address
    # FC_address = get_application_address(fc_id)

    # Get staking contract address
    SC_address = get_application_address(sc_id)

    cc_state = read_global_state(algod_client, fc_id)
    lcd = cc_state["LCD"]

    if lcd == cfg.LAST_COMPOUND_NOT_DONE:
        # There are 12 txs: call to CC, staking asset transfer to CC creator, reward asset transfer to CC creator,
        # clear state from SC, and account close out transaction to CC creator, and initial claiming and unstaking from
        # SC
        num_fees = 5 + 4 + 3
    else:
        # There are 5 txs: call to CC, staking asset transfer to CC creator, reward asset transfer to CC creator,
        # clear state from SC, and account close out transaction to CC creator
        num_fees = 5

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(creatorSK)

    sp.flat_fee = True

    sp.fee = num_fees * sp.min_fee

    tx = transaction.ApplicationDeleteTxn(
        sender=creator_address,
        sp=sp,
        index=fc_id,
        app_args=None,
        accounts=[SC_address],
        foreign_assets=[s_asa_id, r_asa_id],
        foreign_apps=[sc_id, ac_id]
    )
    tws = TransactionWithSigner(tx, signer)
    atc.add_transaction(tws)

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def stakeFarmCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    fc_id: int,
    sc_id: int,
    ac_id: int,
    s_asa_id: int,
    r_asa_id: int,
    p_addr: str,
    amm_id: int,
    stake_amt: int
):
    user_address = account.address_from_private_key(userSK)

    # To stake, it is first necessary to claim all compounded amounts by checking all the boxes; unless you have a zero
    # stake
    cc_local_state = read_local_state(algod_client, user_address, fc_id)
    if int.from_bytes(cc_local_state["LS"], 'big') != 0:
        print("\tClaiming rewards before additional stake can be deposited ...")
        localClaimCompoundContract(algod_client, userSK, fc_id)
        print("\tFinished claiming rewards.")
        print("\tDepositing additional stake...")

    # Get farm compound contract address
    FC_address = get_application_address(fc_id)
    # Get staking contract address
    SC_address = get_application_address(sc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    sp.flat_fee = True
    # There are 3 txs: fund the contract for covering of fees, transfer of assets, and call to FC (other fees are paid
    # from the funding transaction)
    sp.fee = 3 * sp.min_fee

    # Fund the compound contract with enough funds to cover the fees for at least one compounding. Depending on the
    # state (e.g. if somebody has already deposit a stake for the first time or the pool is live), the fees might be
    # higher.
    current_round = algod_client.status().get('last-round')
    cc_state = read_global_state(algod_client, fc_id)
    pool_start_round = cc_state["PSR"]
    total_stake = cc_state["TS"]
    if current_round > pool_start_round and total_stake > 0:
        amt = cfg.FC_FEE_FOR_COMPOUND * 2
    else:
        amt = cfg.FC_FEE_FOR_COMPOUND + cfg.STAKE_TO_SC_FEE

    fund_tx = transaction.PaymentTxn(
        sender=user_address,
        sp=sp,
        receiver=FC_address,
        amt=amt,
    )
    tws = TransactionWithSigner(fund_tx, signer)

    atc.add_transaction(tws)
    sp.fee = 0

    # Transfer the amount wished to be staked
    axfr_tx = transaction.AssetTransferTxn(
        sender=user_address,
        sp=sp,
        receiver=FC_address,
        amt=stake_amt,
        index=s_asa_id
    )
    tws = TransactionWithSigner(axfr_tx, signer)

    atc.add_transaction(tws)

    # Staking can potentially create a new box, thus supply it preemptively
    #  Get current number of boxes in the contract
    num_boxes = read_global_state(algod_client, fc_id).get("NB")
    if not isinstance(num_boxes, int):
        raise Exception("Box supplied not int! " + str(num_boxes))
    box_array = [(0, (num_boxes + 1).to_bytes(8, 'big'))]

    # Make the app call
    atc.add_method_call(
        app_id=fc_id,
        method=cfg.FC_contract.get_method_by_name("stake"),
        sender=user_address,
        sp=sp,
        signer=signer,
        method_args=None,
        foreign_assets=[s_asa_id, r_asa_id],
        foreign_apps=[sc_id, ac_id, amm_id],
        accounts=[SC_address, p_addr],
        boxes=box_array
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def withdrawFarmCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    fc_id: int,
    sc_id: int,
    ac_id: int,
    s_asa_id: int,
    r_asa_id: int,
    p_addr: str,
    amm_id: int,
    withdraw_amt: int
):
    user_address = account.address_from_private_key(userSK)

    # To withdraw, it is first necessary to claim all compounded amounts by checking all the boxes; unless you have
    # already claimed all
    cc_local_state = read_local_state(algod_client, user_address, fc_id)
    cc_global_state = read_global_state(algod_client, fc_id)
    if cc_local_state["LNB"] != cc_global_state["NB"]:
        print("\tClaiming rewards before withdrawing can be done ...")
        localClaimCompoundContract(algod_client, userSK, fc_id)
        print("\tFinished claiming rewards.")
        print("\tWithdrawing requested amount...")
    # Only now it is really possible to withdraw - could still fail if another compounding happened while the user has
    # been locally claiming! In this case, the processes of local claiming needs to be repeated. That can be stalled at
    # most up to the end of the pool.


    # Get farm compound contract address
    FC_address = get_application_address(fc_id)
    # Get staking contract address
    SC_address = get_application_address(sc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    sp.flat_fee = True
    # There are 3 txs: fund the contract for covering of fees, call to FC, and sending of S_ASA from CC.address to user
    sp.fee = 3 * sp.min_fee

    # Fund the compound contract with enough funds to cover the withdrawal. Depending on the state (e.g. if pool has not
    # yet started, is ongoing, has ended and somebody has already compounded the last amount or not), the fees can be
    # different.
    current_round = algod_client.status().get('last-round')
    cc_state = read_global_state(algod_client, fc_id)
    pool_start_round = cc_state["PSR"]
    pool_end_round = cc_state["PER"]
    last_compound_done = cc_state["LCD"]
    if current_round < pool_start_round:
        amt = cfg.UNSTAKE_FROM_SC_FEE
    else:
        if current_round <= pool_end_round:
            amt = cfg.FC_FEE_FOR_COMPOUND + cfg.UNSTAKE_FROM_SC_FEE
        else:
            if last_compound_done == cfg.LAST_COMPOUND_NOT_DONE:
                amt = cfg.FC_FEE_FOR_COMPOUND + cfg.UNSTAKE_FROM_SC_FEE
            else:
                amt = 0

    fund_tx = transaction.PaymentTxn(
        sender=user_address,
        sp=sp,
        receiver=FC_address,
        amt=amt,
    )
    tws = TransactionWithSigner(fund_tx, signer)

    atc.add_transaction(tws)
    sp.fee = 0

    args = [withdraw_amt]

    # Withdrawal can potentially create a new box, thus supply it preemptively
    #  Get current number of boxes in the contract
    num_boxes = read_global_state(algod_client, fc_id).get("NB")
    box_array = [(0, (num_boxes + 1).to_bytes(8, 'big'))]

    # Make the app call
    atc.add_method_call(
        app_id=fc_id,
        method=cfg.FC_contract.get_method_by_name("withdraw"),
        sender=user_address,
        sp=sp,
        signer=signer,
        method_args=args,
        foreign_assets=[s_asa_id, r_asa_id],
        foreign_apps=[sc_id, ac_id, amm_id],
        accounts=[SC_address, p_addr],
        boxes=box_array
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    for res in result.abi_results:
        ret_val = res.return_value
        print("\tReturn value: " + str(ret_val))

    return result.abi_results[0].return_value


def triggerFarmCompoundingCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    fc_id: int,
    sc_id: int,
    ac_id: int,
    s_asa_id: int,
    r_asa_id: int,
    p_addr: str,
    amm_id: int,
):
    user_address = account.address_from_private_key(userSK)
    # Get farm compound contract address
    FC_address = get_application_address(fc_id)
    # Get staking contract address
    SC_address = get_application_address(sc_id)

    next_trig_round = getFarmTriggerRound(algod_client, fc_id)
    if next_trig_round > 0:
        print("\tCompounding is not scheduled for the current round.")
        print("\tNext scheduled trigger at round: " + str(next_trig_round))
        print("\tTip: you can add funds to trigger the contract now.")
        return 0
    elif next_trig_round == -1:
        print("\tCompounding can't be triggered because the pool has already ended.")
        return 0
    elif next_trig_round == -2:
        print("\tCompounding can't be triggered because there is not stake in the pool.")
        return 0
    elif next_trig_round == -3:
        # Next compounding would be after pool end, where it's not necessary anymore
        print("\tThere are no more triggers scheduled before pool end.")
        return 0

    CC_state = read_global_state(algod_client, fc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    # Compounding can potentially create a new box, thus supply it preemptively
    #  Get current number of boxes in the contract
    num_boxes = CC_state.get("NB")
    box_array = [(0, (num_boxes + 1).to_bytes(8, 'big'))]

    # Make the app call
    atc.add_method_call(
        app_id=fc_id,
        method=cfg.FC_contract.get_method_by_name("trigger_compound"),
        sender=user_address,
        sp=sp,
        signer=signer,
        method_args=None,
        foreign_assets=[r_asa_id, s_asa_id],
        foreign_apps=[sc_id, ac_id, amm_id],
        accounts=[p_addr, FC_address],
        boxes=box_array
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return 1


def compoundNowFarmCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    fc_id: int,
    sc_id: int,
    ac_id: int,
    s_asa_id: int,
    r_asa_id: int,
    p_addr: str,
    amm_id: int,
):
    user_address = account.address_from_private_key(userSK)

    # Get farm compound contract address
    FC_address = get_application_address(fc_id)
    # Get staking contract address
    SC_address = get_application_address(sc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    sp.flat_fee = True
    # There are 2 txs: fund the contract for covering of fees, and call to FC (other fees are paid from the funding
    # transaction)
    sp.fee = 2 * sp.min_fee

    # Fund the compound contract with enough funds to cover the fees for the compounding.
    amt = cfg.FC_FEE_FOR_COMPOUND

    fund_tx = transaction.PaymentTxn(
        sender=user_address,
        sp=sp,
        receiver=FC_address,
        amt=amt,
    )
    tws = TransactionWithSigner(fund_tx, signer)

    atc.add_transaction(tws)
    sp.fee = 0

    # Compounding will create a new box, thus supply it preemptively
    #  Get current number of boxes in the contract
    num_boxes = read_global_state(algod_client, fc_id).get("NB")
    box_array = [(0, (num_boxes + 1).to_bytes(8, 'big'))]

    # Make the app call
    atc.add_method_call(
        app_id=fc_id,
        method=cfg.FC_contract.get_method_by_name("compound_now"),
        sender=user_address,
        sp=sp,
        signer=signer,
        method_args=None,
        foreign_assets=[s_asa_id, r_asa_id],
        foreign_apps=[sc_id, ac_id, amm_id],
        accounts=[SC_address, p_addr],
        boxes=box_array
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def getFarmTriggerRound(
    algod_client: algod.AlgodClient,
    cc_id: int
):
    try:
        # Get compound contract address
        CC_address = get_application_address(cc_id)

        # Check if compounding can be triggered
        CC_info = algod_client.account_info(CC_address)
        CC_balance = CC_info.get("amount")
        CC_MRB = CC_info.get("min-balance")
        currentRound = algod_client.status().get('last-round')
        CC_state = read_global_state(algod_client, cc_id)
        num_triggers = math.floor((CC_balance - CC_MRB) / cfg.FC_FEE_FOR_COMPOUND)

        if num_triggers != 0:
            next_compound_round = math.floor((CC_state["PER"] - CC_state["LCR"]) / num_triggers) + CC_state["LCR"]
            if next_compound_round >= CC_state["PER"]:
                return -3
            else:
                if CC_state["LCR"] > CC_state["PER"]:
                    return -1
                else:
                    if next_compound_round <= currentRound:
                        return 0
                    else:
                        return next_compound_round
        else:
            return -2

    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
        return None
    except KeyError:
        print("\tAre you really accessing a compounding contract?")
        return None


