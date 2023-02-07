# -----------------           Imports          -----------------
import base64
import glob
import math
from math import ceil
from decimal import *

from algosdk.v2client import algod, indexer
from algosdk import account, mnemonic, error, transaction
from algosdk.abi import Contract
from algosdk import encoding
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, AccountTransactionSigner, \
    TransactionWithSigner
from algosdk.logic import get_application_address

from util import *

import src.config as cfg

# ---------------------------------------------------------------

def createCompoundContract(
    algod_client: algod.AlgodClient,
    creatorSK: str,
    sc_id: int,
    ac_id: int,
    cp: int
):
    creator_address = account.address_from_private_key(creatorSK)

    # Declare application state storage (immutable)
    global_schema = transaction.StateSchema(cfg.CC_NUM_GLOBAL_UINT, cfg.CC_NUM_GLOBAL_BYTES)
    local_schema = transaction.StateSchema(cfg.CC_NUM_LOCAL_UINT, cfg.CC_NUM_LOCAL_BYTES)

    app_args = [
        sc_id,
        ac_id,
        cp
    ]

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(creatorSK)

    # Simple call to the `create_app` method, method_args can be any type but _must_
    # match those in the method signature of the contract
    atc.add_method_call(
        app_id=0,
        method=cfg.CC_contract.get_method_by_name("create_app"),
        sender=creator_address,
        sp=sp,
        signer=signer,
        approval_program=cfg.CC_approval_program,
        clear_program=cfg.CC_clear_state_program,
        local_schema=local_schema,
        global_schema=global_schema,
        method_args=app_args,
        # extra_pages=cfg.CC_ExtraProgramPages,
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
    a_id = cc_state["S_ASA_ID"]

    return [app_id, a_id]


def setupCompoundContract(
    algod_client: algod.AlgodClient,
    creatorSK: str,
    cc_id: int,
    sc_id: int,
    a_id: int
):
    creator_address = account.address_from_private_key(creatorSK)

    # Get compound contract address
    CC_address = get_application_address(cc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(creatorSK)

    sp.flat_fee = True
    # There are 4 txs: fund the contract for opt-ins, call to CC, SC opt-in, and ASA opt-in
    sp.fee = 4 * sp.min_fee

    # Fund the compound contract with minimal balance to opt-in to the staking contract and ASA
    # Minimal balance: minimal balance for any account + minimal balance for 1 ASA + for opt-in to staking contract (not
    # exactly sure about the amount since it is in Reach - just one Byte slice? = 25_000 + 25_000; seems to be 3 slices)
    amt = 100_000 + 100_000 + 50_000*3

    fund_tx = transaction.PaymentTxn(
        sender=creator_address,
        sp=sp,
        receiver=CC_address,
        amt=amt,
    )
    tws = TransactionWithSigner(fund_tx, signer)

    atc.add_transaction(tws)
    sp.fee = 0

    app_args = []
    # Call to the `on_setup` method
    atc.add_method_call(
        app_id=cc_id,
        method=cfg.CC_contract.get_method_by_name("on_setup"),
        sender=creator_address,
        sp=sp,
        signer=signer,
        method_args=app_args,
        foreign_assets=[a_id],
        foreign_apps=[sc_id]
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def deleteCompoundContract(algod_client: algod.AlgodClient,
    creatorSK: str,
    cc_id: int,
    sc_id: int,
    ac_id: int,
    a_id: int
):
    creator_address = account.address_from_private_key(creatorSK)

    # # Get compound contract address
    # CC_address = get_application_address(cc_id)

    # Get staking contract address
    SC_address = get_application_address(sc_id)

    cc_state = read_global_state(algod_client, cc_id)
    lcd = cc_state["LCD"]

    if lcd == cfg.LAST_COMPOUND_NOT_DONE:
        # There are 4 txs: call to CC, asset transfer to CC creator, clear state from SC, and account close out
        # transaction to CC creator, and initial claiming and unstaking from SC
        num_fees = 4 + 4 + 3
    else:
        # There are 4 txs: call to CC, asset transfer to CC creator, clear state from SC, and account close out
        # transaction to CC creator
        num_fees = 4

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(creatorSK)

    sp.flat_fee = True

    sp.fee = num_fees * sp.min_fee

    tx = transaction.ApplicationDeleteTxn(
        sender=creator_address,
        sp=sp,
        index=cc_id,
        app_args=None,
        accounts=[SC_address],
        foreign_assets=[a_id],
        foreign_apps=[sc_id, ac_id]
    )
    tws = TransactionWithSigner(tx, signer)
    atc.add_transaction(tws)

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def deleteAllBoxes(
    algod_client: algod.AlgodClient,
    creatorSK: str,
    cc_id: int
):
    creator_address = account.address_from_private_key(creatorSK)

    # Number of boxes in a batch to process
    BB = 7

    # Get current number of boxes in the contract
    curr_boxes = read_global_state(algod_client, cc_id).get("NB")

    if curr_boxes < 1:
        raise Exception("There are no boxes, thus none can be deleted.")

    # Process all of them
    while curr_boxes > 0:

        sp = algod_client.suggested_params()
        atc = AtomicTransactionComposer()
        signer = AccountTransactionSigner(creatorSK)

        g = 0

        while g < 16 and curr_boxes > 0:
            # Process them in batches - try to add as many in a single group (i.e. max 16)
            down_to = curr_boxes - BB
            if down_to < 0:
                down_to = 0

            app_args = [down_to]

            # Generate box array
            box_array = [(0, x.to_bytes(8, 'big')) for x in range(curr_boxes, down_to, -1)]

            # Call to the `delete_boxes` method
            atc.add_method_call(
                app_id=cc_id,
                method=cfg.CC_contract.get_method_by_name("delete_boxes"),
                sender=creator_address,
                sp=sp,
                signer=signer,
                method_args=app_args,
                foreign_assets=None,
                foreign_apps=None,
                boxes=box_array
            )

            g += 1
            curr_boxes = down_to

        log_gtx(atc.build_group())
        result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

        for res in result.tx_ids:
            print("\tTx ID: " + res)

    return


def optinCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    cc_id: int
):
    user_address = account.address_from_private_key(userSK)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    tx = transaction.ApplicationOptInTxn(
        sender=user_address,
        sp=sp,
        index=cc_id
    )
    tws = TransactionWithSigner(tx, signer)
    atc.add_transaction(tws)

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def optoutCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    cc_id: int
):
    user_address = account.address_from_private_key(userSK)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    tx = transaction.ApplicationCloseOutTxn(
        sender=user_address,
        sp=sp,
        index=cc_id
    )
    tws = TransactionWithSigner(tx, signer)
    atc.add_transaction(tws)

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def clearStateCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    cc_id: int
):
    user_address = account.address_from_private_key(userSK)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    tx = transaction.ApplicationClearStateTxn(
        sender=user_address,
        sp=sp,
        index=cc_id
    )
    tws = TransactionWithSigner(tx, signer)
    atc.add_transaction(tws)

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def stakeCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    cc_id: int,
    sc_id: int,
    ac_id: int,
    a_id: int,
    stake_amt: int
):
    user_address = account.address_from_private_key(userSK)

    # To stake, it is first necessary to claim all compounded amounts by checking all the boxes; unless you have a zero
    # stake
    cc_local_state = read_local_state(algod_client, user_address, cc_id)
    if int.from_bytes(cc_local_state["LS"], 'big') != 0:
        print("\tClaiming rewards before additional stake can be deposited ...")
        localClaimCompoundContract(algod_client, userSK, cc_id)
        print("\tFinished claiming rewards.")
        print("\tDepositing additional stake...")

    # Get compound contract address
    CC_address = get_application_address(cc_id)
    # Get staking contract address
    SC_address = get_application_address(sc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    sp.flat_fee = True
    # There are 3 txs: fund the contract for covering of fees, transfer of assets, and call to CC (other fees are paid
    # from the funding transaction)
    sp.fee = 3 * sp.min_fee

    # Fund the compound contract with enough funds to cover the fees for at least one compounding. Depending on the
    # state (e.g. if somebody has already deposit a stake for the first time or the pool is live), the fees might be
    # higher.
    current_round = algod_client.status().get('last-round')
    cc_state = read_global_state(algod_client, cc_id)
    pool_start_round = cc_state["PSR"]
    total_stake = cc_state["TS"]
    if current_round > pool_start_round and total_stake > 0:
        amt = cfg.CC_FEE_FOR_COMPOUND * 2
    else:
        amt = cfg.CC_FEE_FOR_COMPOUND + cfg.STAKE_TO_SC_FEE

    fund_tx = transaction.PaymentTxn(
        sender=user_address,
        sp=sp,
        receiver=CC_address,
        amt=amt,
    )
    tws = TransactionWithSigner(fund_tx, signer)

    atc.add_transaction(tws)
    sp.fee = 0

    # Transfer the amount wished to be staked
    axfr_tx = transaction.AssetTransferTxn(
        sender=user_address,
        sp=sp,
        receiver=CC_address,
        amt=stake_amt,
        index=a_id
    )
    tws = TransactionWithSigner(axfr_tx, signer)

    atc.add_transaction(tws)

    # Staking can potentially create a new box, thus supply it preemptively
    #  Get current number of boxes in the contract
    num_boxes = read_global_state(algod_client, cc_id).get("NB")
    if not isinstance(num_boxes, int):
        raise Exception("Box supplied not int! " + str(num_boxes))
    box_array = [(0, (num_boxes + 1).to_bytes(8, 'big'))]

    # Make the app call
    atc.add_method_call(
        app_id=cc_id,
        method=cfg.CC_contract.get_method_by_name("stake"),
        sender=user_address,
        sp=sp,
        signer=signer,
        method_args=None,
        foreign_assets=[a_id],
        foreign_apps=[sc_id, ac_id],
        accounts=[SC_address],
        boxes=box_array
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def localClaimCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    cc_id: int
):
    user_address = account.address_from_private_key(userSK)

    # Number of boxes in a batch to process
    BB = 7

    while True:

        # Get current number of boxes in the contract
        cc_state = read_global_state(algod_client, cc_id)
        curr_boxes = cc_state["NB"]
        # Get local current number of boxes in the contract
        local_boxes = read_local_state(algod_client, user_address, cc_id).get("LNB")

        box_missing = curr_boxes - local_boxes
        if box_missing == 0:
            break
        elif box_missing < 0:
            raise Exception("Unfortunately you were too late to claim your stake...")
        else:
            sp = algod_client.suggested_params()
            atc = AtomicTransactionComposer()
            signer = AccountTransactionSigner(userSK)

            g = 0

            while g < 16 and box_missing > 0:
                # Process them in batches - try to group as many (i.e. max 16)
                if box_missing < BB:
                    up_to = curr_boxes
                else:
                    up_to = local_boxes + BB

                app_args = [up_to]

                # Generate box array
                box_array = [(0, x.to_bytes(8, 'big')) for x in range(local_boxes+1, up_to+1, +1)]

                # Call to the `local_claim` method
                atc.add_method_call(
                    app_id=cc_id,
                    method=cfg.CC_contract.get_method_by_name("local_claim"),
                    sender=user_address,
                    sp=sp,
                    signer=signer,
                    method_args=app_args,
                    foreign_assets=None,
                    foreign_apps=None,
                    boxes=box_array
                )

                g += 1
                local_boxes = up_to
                box_missing = curr_boxes - local_boxes

            log_gtx(atc.build_group())
            result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

            for res in result.tx_ids:
                print("\tTx ID: " + res)

    return


def withdrawCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    cc_id: int,
    sc_id: int,
    ac_id: int,
    a_id: int,
    withdraw_amt: int
):
    user_address = account.address_from_private_key(userSK)

    # To withdraw, it is first necessary to claim all compounded amounts by checking all the boxes; unless you have
    # already claimed all
    cc_local_state = read_local_state(algod_client, user_address, cc_id)
    cc_global_state = read_global_state(algod_client, cc_id)
    if cc_local_state["LNB"] != cc_global_state["NB"]:
        print("\tClaiming rewards before withdrawing can be done ...")
        localClaimCompoundContract(algod_client, userSK, cc_id)
        print("\tFinished claiming rewards.")
        print("\tWithdrawing requested amount...")
    # Only now it is really possible to withdraw - could still fail if another compounding happened while the user has
    # been locally claiming! In this case, the processes of local claiming needs to be repeated. That can be stalled at
    # most up to the end of the pool.


    # Get compound contract address
    CC_address = get_application_address(cc_id)
    # Get staking contract address
    SC_address = get_application_address(sc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    sp.flat_fee = True
    # There are 3 txs: fund the contract for covering of fees, call to CC, and sending of ASA from CC.address to user
    sp.fee = 3 * sp.min_fee

    # Fund the compound contract with enough funds to cover the withdrawal. Depending on the state (e.g. if pool has not
    # yet started, is ongoing, has ended and somebody has already compounded the last amount or not), the fees can be
    # different.
    current_round = algod_client.status().get('last-round')
    cc_state = read_global_state(algod_client, cc_id)
    pool_start_round = cc_state["PSR"]
    pool_end_round = cc_state["PER"]
    last_compound_done = cc_state["LCD"]
    if current_round < pool_start_round:
        amt = cfg.UNSTAKE_FROM_SC_FEE
    else:
        if current_round <= pool_end_round:
            amt = cfg.CC_FEE_FOR_COMPOUND + cfg.UNSTAKE_FROM_SC_FEE
        else:
            if last_compound_done == cfg.LAST_COMPOUND_NOT_DONE:
                amt = cfg.CC_FEE_FOR_COMPOUND + cfg.UNSTAKE_FROM_SC_FEE
            else:
                amt = 0

    fund_tx = transaction.PaymentTxn(
        sender=user_address,
        sp=sp,
        receiver=CC_address,
        amt=amt,
    )
    tws = TransactionWithSigner(fund_tx, signer)

    atc.add_transaction(tws)
    sp.fee = 0

    args = [withdraw_amt]

    # Withdrawal can potentially create a new box, thus supply it preemptively
    #  Get current number of boxes in the contract
    num_boxes = read_global_state(algod_client, cc_id).get("NB")
    box_array = [(0, (num_boxes + 1).to_bytes(8, 'big'))]

    # Make the app call
    atc.add_method_call(
        app_id=cc_id,
        method=cfg.CC_contract.get_method_by_name("withdraw"),
        sender=user_address,
        sp=sp,
        signer=signer,
        method_args=args,
        foreign_assets=[a_id],
        foreign_apps=[sc_id, ac_id],
        accounts=[SC_address],
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


def triggerCompoundingCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    cc_id: int,
    sc_id: int,
    ac_id: int,
    a_id: int
):
    user_address = account.address_from_private_key(userSK)
    # Get compound contract address
    CC_address = get_application_address(cc_id)
    # Get staking contract address
    SC_address = get_application_address(sc_id)

    next_trig_round = getTriggerRound(algod_client, cc_id)
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

    CC_state = read_global_state(algod_client, cc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    # Compounding can potentially create a new box, thus supply it preemptively
    #  Get current number of boxes in the contract
    num_boxes = CC_state.get("NB")
    box_array = [(0, (num_boxes + 1).to_bytes(8, 'big'))]

    # Make the app call
    atc.add_method_call(
        app_id=cc_id,
        method=cfg.CC_contract.get_method_by_name("trigger_compound"),
        sender=user_address,
        sp=sp,
        signer=signer,
        method_args=None,
        foreign_assets=[a_id],
        foreign_apps=[sc_id, ac_id],
        accounts=[CC_address, SC_address],
        boxes=box_array
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return 1


def compoundNowCompoundContract(
    algod_client: algod.AlgodClient,
    userSK: str,
    cc_id: int,
    sc_id: int,
    ac_id: int,
    a_id: int
):
    user_address = account.address_from_private_key(userSK)

    # Get compound contract address
    CC_address = get_application_address(cc_id)
    # Get staking contract address
    SC_address = get_application_address(sc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    sp.flat_fee = True
    # There are 2 txs: fund the contract for covering of fees, and call to CC (other fees are paid from the funding
    # transaction)
    sp.fee = 2 * sp.min_fee

    # Fund the compound contract with enough funds to cover the fees for the compounding.
    amt = cfg.CC_FEE_FOR_COMPOUND

    fund_tx = transaction.PaymentTxn(
        sender=user_address,
        sp=sp,
        receiver=CC_address,
        amt=amt,
    )
    tws = TransactionWithSigner(fund_tx, signer)

    atc.add_transaction(tws)
    sp.fee = 0

    # Compounding will create a new box, thus supply it preemptively
    #  Get current number of boxes in the contract
    num_boxes = read_global_state(algod_client, cc_id).get("NB")
    box_array = [(0, (num_boxes + 1).to_bytes(8, 'big'))]

    # Make the app call
    atc.add_method_call(
        app_id=cc_id,
        method=cfg.CC_contract.get_method_by_name("compound_now"),
        sender=user_address,
        sp=sp,
        signer=signer,
        method_args=None,
        foreign_assets=[a_id],
        foreign_apps=[sc_id, ac_id],
        accounts=[SC_address],
        boxes=box_array
    )

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def sheduleAdditionalCompounding(
    algod_client: algod.AlgodClient,
    userSK: str,
    cc_id: int
):
    # Scheduling additional optimal compounding is done automatically by simply depositing another fee for triggering
    # The whole schedule is optimized
    user_address = account.address_from_private_key(userSK)

    # Get compound contract address
    CC_address = get_application_address(cc_id)

    sp = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(userSK)

    # Fund the compound contract with enough funds to cover the fees for a compounding
    amt = cfg.CC_FEE_FOR_COMPOUND

    fund_tx = transaction.PaymentTxn(
        sender=user_address,
        sp=sp,
        receiver=CC_address,
        amt=amt,
    )
    tws = TransactionWithSigner(fund_tx, signer)
    atc.add_transaction(tws)

    log_gtx(atc.build_group())
    result = atc.execute(algod_client, cfg.TX_APPROVAL_WAIT)

    for res in result.tx_ids:
        print("\tTx ID: " + res)

    return


def getUsersCompoundStake(
    algod_client: algod.AlgodClient,
    user_address: str,
    cc_id: int
):

    try:
        # Get current number of boxes in the contract
        cc_state = read_global_state(algod_client, cc_id)
        curr_boxes = cc_state["NB"]
        # Get local current number of boxes in the contract
        cc_local_state = read_local_state(algod_client, user_address, cc_id)
        local_boxes = cc_local_state.get("LNB")

        # Get user's local stake
        ls_bytes = cc_local_state.get("LS")
        local_stake = Decimal(int.from_bytes(ls_bytes, 'big'))

        # Go through each yet unclaimed box and compound the result
        for box in range(local_boxes + 1, curr_boxes + 1, +1):
            # Fetch the increase amount from the box
            increment = algod_client.application_box_by_name(cc_id, box.to_bytes(8, 'big'))
            increment = Decimal(int.from_bytes(base64.b64decode(increment.get("value")), 'big'))\
                        / Decimal(2 ** (8 * cfg.LOCAL_STAKE_N))

            local_stake = local_stake*increment

        return (Decimal(local_stake) / Decimal(2 ** (8 * cfg.LOCAL_STAKE_N))).quantize(Decimal('1'), rounding=ROUND_DOWN)

    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
        return None
    except KeyError:
        print("\nYou are not opted into the contract!")
        return None


def readAllCompoundingContributions(
    algod_client: algod.AlgodClient,
    cc_id: int
):

    try:
        print("\nIncrements from compoundings:")
        # Get current number of boxes in the contract
        cc_state = read_global_state(algod_client, cc_id)
        curr_boxes = cc_state["NB"]

        if curr_boxes == 0:
            print('\t There has been no compounding done yet')
            return

        # Go through each box and print the increment
        for box in range(1, curr_boxes + 1, +1):
            # Fetch the increase amount from the box
            increment = algod_client.application_box_by_name(cc_id, box.to_bytes(8, 'big'))
            increment_float = Decimal(int.from_bytes(base64.b64decode(increment.get("value")), 'big')) \
                              / Decimal(2 ** (8 * cfg.LOCAL_STAKE_N))

            print("\tBox number {:04d}: b64='{}' = {:.30f}".format(box, increment.get("value"), increment_float))

    except error.AlgodHTTPError as e:
        print("\tError: " + str(e))
    except KeyError:
        print("\nYou are not opted into the contract!")

def getTriggerRound(
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
        num_triggers = math.floor((CC_balance - CC_MRB) / cfg.CC_FEE_FOR_COMPOUND)

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
