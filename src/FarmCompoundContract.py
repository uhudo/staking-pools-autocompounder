import math

from pyteal import *
from typing import Literal
from util import *
from src.config import *
from algosdk.v2client import algod


# -----    Address of Staking Contract      -----
SC_address = AppParam.address(App.globalGet(CC_SC_ID))

# -----    Subroutines    -----
# floor_local_stake() -> Expr:
# Get rounded down integer amount of user's local stake
#
@Subroutine(TealType.uint64)
def floor_local_stake() -> Expr:
    # Variable for storing the local stake
    ls = ScratchVar()

    return Seq(
        ls.store(App.localGet(Txn.sender(), CC_local_stake)),
        If(
            Len(ls.load()) > Int(LOCAL_STAKE_N)
        ).Then(
            Btoi(Extract(ls.load(), Int(0), Len(ls.load()) - Int(LOCAL_STAKE_N)))
        ).Else(
            Int(0)
        )
    )

# closeAccountTo(account: Expr) -> Expr:
#  Sends remaining balance of the application account to a specified account, i.e. it closes the application account.
#  Fee for the inner transaction is set to zero, thus fee pooling needs to be used.
#
@Subroutine(TealType.none)
def closeAccountTo(account: Expr) -> Expr:
    return If(Balance(Global.current_application_address()) != Int(0)).Then(
        Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.fee: Int(0),
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.close_remainder_to: account,
                }
            ),
            InnerTxnBuilder.Submit(),
        )
    )

# payTo(account: Expr, amount: Expr) -> Expr:
#  Sends a payment transaction of amount to account
#
@Subroutine(TealType.none)
def payTo(account: Expr, amount: Expr) -> Expr:
    return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.fee: Int(0),
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: account,
                    TxnField.amount: amount
                }
            ),
            InnerTxnBuilder.Submit(),
        )

# closeAssetToCreator(ASA_ID: Expr) -> Expr:
#  Sends whole amount of ASA_ID to FC creator
#
@Subroutine(TealType.none)
def closeAssetToCreator(ASA_ID: Expr) -> Expr:
    return Seq(
        InnerTxnBuilder.Execute(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: ASA_ID,
                TxnField.asset_close_to: Global.creator_address(),
                TxnField.fee: Int(0),
            }
        )
    )

# stake_to_SC(amt: Expr, payFee: Expr) -> Expr:
#  Issue app call to SC to stake additional S_ASA_ID amount 'amt'
#  If payFee == PAY_FEE, FC.address will pay the fee for the staking operation. Otherwise, the fee needs to be pooled.
#
@Subroutine(TealType.none)
def stake_to_SC(amt: Expr, payFee: Expr) -> Expr:
    return Seq(
        # Assert address of SC
        SC_address,
        Assert(SC_address.hasValue()),
        # Stake to SC
        InnerTxnBuilder.Begin(),
        #  First create an asset transfer transaction
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(CC_S_ASA_ID),
                TxnField.asset_receiver: SC_address.value(),
                TxnField.asset_amount: amt,
                TxnField.fee: Int(0),
            }
        ),
        InnerTxnBuilder.Next(),
        #  Then create an app call to stake
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.ApplicationCall,
                TxnField.application_id: App.globalGet(CC_SC_ID),
                TxnField.applications: [App.globalGet(CC_AC_ID)],
                TxnField.assets: [App.globalGet(CC_S_ASA_ID)],
                TxnField.accounts: [SC_address.value()],
                TxnField.on_completion: OnComplete.NoOp,
                TxnField.application_args: [
                    Bytes("base64", "AA=="),
                    Bytes("base64", "Aw=="),
                    Bytes("base64", "AAAAAAAAAAA="),
                    Concat(Bytes("base16", "0x02"), Itob(amt)),
                ],
                TxnField.fee: If(
                    payFee == Int(PAY_FEE),
                ).Then(
                    Int(STAKE_TO_SC_FEE),
                ).Else(
                    Int(0),
                )
            }
        ),
        #  Submit the created group transaction
        InnerTxnBuilder.Submit(),
    )

# claim_stake_record(amt: Expr, payFee: Expr) -> Expr:
#  First, claim R_ASA_ID rewards from SC.
#  Secondly, zap the claimed amount into P_ADDR pool of AMM_ID.
#  Then create the recording of the received new pool tokens by storing it in a newly created box.
#  Lastly, stake the new tokens plus any additional amount of S_ASA_ID to SC, and update the total stake as well as the
#  last  compound round.
#  If payFee == PAY_FEE, FC.address will pay the fee for the operations. Otherwise, the fee needs to be pooled.
#
@Subroutine(TealType.none)
def claim_stake_record(amt: Expr, payFee: Expr) -> Expr:

    # Variable for calculating how much pool tokens S_ASA_ID did adding liquidity provide
    S_ASA_increase = ScratchVar()

    # Variable for storing the claimed R_ASA_ID amount
    claim_amt = ScratchVar()

    # Variable for storing the amount of S_ASA_ID to stake
    stake_amt = ScratchVar()

    # Boxes are sequentially numbered
    box_name = Itob(App.globalGet(CC_number_of_boxes))

    # Amount of increase: 1 + (claim_amt / total stake)
    increase = BytesAdd(
        Concat(Itob(Int(1)), BytesZero(Int(LOCAL_STAKE_N))),
        BytesDiv(
            Concat(Itob(S_ASA_increase.load()), BytesZero(Int(LOCAL_STAKE_N))),
            Concat(BytesZero(Int(LOCAL_STAKE_N)), Itob(App.globalGet(CC_total_stake)))
        )
    )

    # FC_S_ADA_ID_balance
    get_FC_S_ASA_ID_balance = AssetHolding.balance(Global.current_application_address(), App.globalGet(CC_S_ASA_ID))

    # FC_R_ADA_ID_balance
    get_FC_R_ASA_ID_balance = AssetHolding.balance(Global.current_application_address(), App.globalGet(FC_R_ASA_ID))

    return Seq(
        # Claiming makes sense only if current total stake was non-zero
        Assert(App.globalGet(CC_total_stake) > Int(0)),
        # Assert address of SC
        SC_address,
        Assert(SC_address.hasValue()),
        # Store S_ASA_ID balance of FC.addr (which is surely opted into the contract)
        get_FC_S_ASA_ID_balance,
        S_ASA_increase.store(get_FC_S_ASA_ID_balance.value()),
        # Claim R_ASA_ID from SC
        InnerTxnBuilder.Execute(
            {
                TxnField.type_enum: TxnType.ApplicationCall,
                TxnField.application_id: App.globalGet(CC_SC_ID),
                TxnField.applications: [App.globalGet(CC_AC_ID)],
                TxnField.assets: [App.globalGet(FC_R_ASA_ID)],
                TxnField.accounts: [SC_address.value()],
                TxnField.on_completion: OnComplete.NoOp,
                TxnField.application_args: [
                    Bytes("base64", "AA=="),
                    Bytes("base64", "Aw=="),
                    Bytes("base64", "AAAAAAAAAAA="),
                    Bytes("base64", "AAAAAAAAAAAA"),
                ],
                TxnField.fee: If(
                    payFee == Int(PAY_FEE)
                ).Then(
                    Int(CLAIM_FROM_SC_FEE),
                ).Else(
                    Int(0),
                )
            }
        ),

        # Store the claimed amount, which is written in the last log of the call claim from SC, 8 bytes starting from
        # byte 16
        claim_amt.store(Btoi(Extract(InnerTxn.last_log(), Int(16), Int(8)))),

        # Single-side add liquidity (i.e. zap) to pool address of AMM_ID if amount of R_ASA_ID is below a minimum
        # threshold `FC_MRAAL`
        get_FC_R_ASA_ID_balance,
        If(get_FC_R_ASA_ID_balance.value() >= App.globalGet(FC_MRAAL)).Then(
            Seq(
                InnerTxnBuilder.Begin(),
                # Create an asset transfer transaction
                InnerTxnBuilder.SetFields(
                    {
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(FC_R_ASA_ID),
                        TxnField.asset_receiver: App.globalGet(FC_P_ADDR),
                        TxnField.asset_amount: get_FC_R_ASA_ID_balance.value(),
                        TxnField.fee: Int(0),
                    }
                ),
                InnerTxnBuilder.Next(),
                # Create an app call to single-side add liquidity at all costs, i.e. expect a minimum of 1 unit returned
                InnerTxnBuilder.SetFields(
                    {
                        TxnField.type_enum: TxnType.ApplicationCall,
                        TxnField.application_id: App.globalGet(FC_AMM_ID),
                        TxnField.assets: [App.globalGet(CC_S_ASA_ID)],
                        TxnField.accounts: [App.globalGet(FC_P_ADDR)],
                        TxnField.on_completion: OnComplete.NoOp,
                        TxnField.application_args: [
                            Bytes("add_liquidity"),
                            Bytes("single"),
                            Itob(Int(1)),
                        ],
                        TxnField.fee: If(
                            payFee == Int(PAY_FEE),
                        ).Then(
                            Int(ZAP_FEE),
                        ).Else(
                            Int(0),
                        )
                    }
                ),
                #  Submit the created group transaction
                InnerTxnBuilder.Submit(),
            )
        ),
        # Calculate the number of received pool tokens S_ASA_ID
        get_FC_S_ASA_ID_balance,
        S_ASA_increase.store(get_FC_S_ASA_ID_balance.value() - S_ASA_increase.load()),

        # Increase the counter of boxes created
        App.globalPut(CC_number_of_boxes, App.globalGet(CC_number_of_boxes) + Int(1)),

        # Create a new box with name equal to the number of boxes and populate it with the increase from this
        # compounding
        App.box_put(box_name, increase),

        # Stake the claimed amount plus any additional stake - if they are non-zero
        stake_amt.store(S_ASA_increase.load() + amt),
        If(stake_amt.load() > Int(0)).Then(
            stake_to_SC(stake_amt.load(), payFee),

            # Update the total stake in CC
            App.globalPut(CC_total_stake, App.globalGet(CC_total_stake) + stake_amt.load()),
        ),

        # Update the round of last compound to current round
        App.globalPut(CC_last_compound_round, Global.round())
    )

# unstake_from_SC(amt: Expr, payFee: Expr) -> Expr:
#  Issue app call to SC to unstake S_ASA_ID amount 'amt'
#  If payFee == PAY_FEE, FC.address will pay the fee for the unstaking operation. Otherwise, the fee needs to be pooled.
#
@Subroutine(TealType.none)
def unstake_from_SC(amt: Expr, payFee: Expr) -> Expr:
    return Seq(
        # Assert address of SC
        SC_address,
        Assert(SC_address.hasValue()),
        # Unstake from SC
        InnerTxnBuilder.Execute(
            {
                TxnField.type_enum: TxnType.ApplicationCall,
                TxnField.application_id: App.globalGet(CC_SC_ID),
                TxnField.applications: [App.globalGet(CC_AC_ID)],
                TxnField.assets: [App.globalGet(CC_S_ASA_ID)],
                TxnField.accounts: [SC_address.value()],
                TxnField.on_completion: OnComplete.NoOp,
                TxnField.application_args: [
                    Bytes("base64", "AA=="),
                    Bytes("base64", "Aw=="),
                    Bytes("base64", "AAAAAAAAAAA="),
                    Concat(Bytes("base16", "0x03"), Itob(amt)),
                ],
                TxnField.fee: If(
                    payFee == Int(PAY_FEE)
                ).Then(
                    Int(UNSTAKE_FROM_SC_FEE),
                ).Else(
                    Int(0),
                )
            }
        ),
    )

# sendAssetToSender(ASA_ID: Expr, amt: Expr) -> Expr:
#  Sends amount amt of ASA_ID to Txn.sender()
#
@Subroutine(TealType.none)
def sendAssetToSender(ASA_ID: Expr, amt: Expr) -> Expr:
    return Seq(
        InnerTxnBuilder.Execute(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: ASA_ID,
                TxnField.asset_amount: amt,
                TxnField.asset_receiver: Txn.sender(),
                TxnField.fee: Int(0),
            }
        )
    )

# local_claim_box(box_i: Expr) -> Expr:
#  Adds amount received by user from a compounding that was done and recorded in box
#
@Subroutine(TealType.none)
def local_claim_box(box_int: Expr) -> Expr:

    # Box name = sequential number of the box (uint64)
    box_name = Itob(box_int)

    # Box contents
    contents = App.box_get(box_name)
    # Get increase from the box
    increase = contents.value()

    return Seq(
        # Assert the box already exists
        contents,
        Assert(contents.hasValue()),
        # Claims must be done in a strictly increasing order, without skipping any claim.
        # This is checked by asserting the local number of boxes is one smaller than the current box_int
        # This is needed to be able to track what has already been (locally) claimed and what not, without having to
        # record this info explicitly for each user.
        Assert(box_int == App.localGet(Txn.sender(), CC_local_number_of_boxes) + Int(1)),

        # Increase local stake for the contribution of the user to the time the compounding has been done,
        # i.e. += (box[round].claimed * LS) / box[round].total_stake_at_time_of_compounding, which equals
        # *= box[round].increase
        App.localPut(Txn.sender(), CC_local_stake, BytesDiv(
                BytesMul(App.localGet(Txn.sender(), CC_local_stake), increase),
                Concat(Itob(Int(1)), BytesZero(Int(LOCAL_STAKE_N)))
            )
        ),

        # Update local number of boxes
        App.localPut(Txn.sender(), CC_local_number_of_boxes, box_int)
    )

# -----     On delete     -----
on_delete = Seq(
    # Only the contract creator can delete the contract
    Assert(Txn.sender() == Global.creator_address()),
    # Only when there are no more accounts opted into the FC and the pool has ended, or the claiming period has passed
    Assert(
        Or(
            And(App.globalGet(CC_number_of_stakers) == Int(0), Global.round() > App.globalGet(CC_pool_end_round)),
            Global.round() > (App.globalGet(CC_pool_end_round) + App.globalGet(CC_claiming_period))
        )
    ),
    # Only when all boxes were deleted
    Assert(App.globalGet(CC_number_of_boxes) == Int(0)),
    # Ensure all funds have either already been claimed from SC to FC or do it now
    If(App.globalGet(CC_last_compound_done) == Int(LAST_COMPOUND_NOT_DONE)).Then(
        Seq(
            # Make a claim to SC
            # Assert address of SC
            SC_address,
            Assert(SC_address.hasValue()),
            # Claim from SC - fees should be pooled
            InnerTxnBuilder.Execute(
                {
                    TxnField.type_enum: TxnType.ApplicationCall,
                    TxnField.application_id: App.globalGet(CC_SC_ID),
                    TxnField.applications: [App.globalGet(CC_AC_ID)],
                    TxnField.assets: [App.globalGet(CC_S_ASA_ID)],
                    TxnField.accounts: [SC_address.value()],
                    TxnField.on_completion: OnComplete.NoOp,
                    TxnField.application_args: [
                        Bytes("base64", "AA=="),
                        Bytes("base64", "Aw=="),
                        Bytes("base64", "AAAAAAAAAAA="),
                        Bytes("base64", "AAAAAAAAAAAA"),
                    ],
                    TxnField.fee: Int(0),
                }
            ),
            # Unstake total stake from SC - fees should be pooled
            unstake_from_SC(App.globalGet(CC_total_stake), Int(DO_NOT_PAY_FEE)),
        )
    ),

    # Close all S_ASA_ID to the FC creator
    closeAssetToCreator(App.globalGet(CC_S_ASA_ID)),
    # Close all R_ASA_ID to the FC creator
    closeAssetToCreator(App.globalGet(FC_R_ASA_ID)),

    # Clear state of FC in SC
    InnerTxnBuilder.Execute(
        {
            TxnField.type_enum: TxnType.ApplicationCall,
            TxnField.on_completion: OnComplete.ClearState,
            TxnField.application_id: App.globalGet(CC_SC_ID),
            TxnField.fee: Int(0),
        }
    ),

    # Close the contract account to the FC creator
    closeAccountTo(Global.creator_address()),
    Approve(),
)

# -----   On close out    -----
on_close_out = Seq(
    # Allow opting out only if user has withdrawn all (integer part) of the stake - otherwise funds would be lost
    Assert(floor_local_stake() == Int(0)),
    # Reduce number of opted-in accounts
    App.globalPut(CC_number_of_stakers, App.globalGet(CC_number_of_stakers) - Int(1)),
    Approve()
)


# -----    On opt in      -----
on_opt_in = Seq(
    # Opt-ins are allowed only until the pool is live
    Assert(App.globalGet(CC_pool_end_round) > Global.round()),
    # Opt-ins are allowed only if the contract has already been setup - which is reflected in last compound round
    Assert(App.globalGet(CC_last_compound_round) > Int(0)),
    # Initialize local state
    App.localPut(Txn.sender(), CC_local_number_of_boxes, App.globalGet(CC_number_of_boxes)),
    App.localPut(Txn.sender(), CC_local_stake, LOCAL_STAKE_ZERO_BYTES),
    # Increase the number of opted-in accounts
    App.globalPut(CC_number_of_stakers, App.globalGet(CC_number_of_stakers) + Int(1)),
    Approve()
)

# -----    Clear state      -----
clear_state = Seq(
    # Note: User will forfeit their stake
    # Reduce number of opted-in accounts
    App.globalPut(CC_number_of_stakers, App.globalGet(CC_number_of_stakers) - Int(1)),
    Approve()
)

# -----    Calculation of next round to compound      -----
number_of_triggers = (Balance(Global.current_application_address()) - MinBalance(Global.current_application_address()))/Int(FC_FEE_FOR_COMPOUND)
next_compound_round = (App.globalGet(CC_pool_end_round) - App.globalGet(CC_last_compound_round))/number_of_triggers + App.globalGet(CC_last_compound_round)


# -----       Router      -----
def getRouter():

    # Main router class
    router = Router(
        # Name of the contract
        "FarmCompoundContract",
        # What to do for each on-complete type when no arguments are passed (bare call)
        BareCallActions(
            # Updating the contract is not allowed
            update_application=OnCompleteAction.always(Reject()),
            # Deleting the contract is allowed in certain cases
            delete_application=OnCompleteAction.call_only(on_delete),
            # Closing out is allowed in certain cases
            close_out=OnCompleteAction.call_only(on_close_out),
            # Clearing the state is discouraged because it will result in loss of funds
            clear_state=OnCompleteAction.call_only(clear_state),
            # Opt-in is always allowed but requires some logic to execute first
            opt_in=OnCompleteAction.call_only(on_opt_in),
        ),
    )


    @router.method(no_op=CallConfig.CREATE)
    def create_app(SC_ID: abi.Uint64, AC_ID: abi.Uint64, P_ADDR: abi.Address, AMM_ID: abi.Uint64,
                   claimPeriod: abi.Uint64, minRewardAmountAddLiquid: abi.Uint64):

        # Get global state of SC at key value of 0x00
        SC_glob_state = App.globalGetEx(App.globalGet(CC_SC_ID), Bytes("base64", "AA=="))

        return Seq(
            # Assert length of pool address
            Assert(Len(P_ADDR.get()) == Int(32)),
            # Set global variables
            App.globalPut(CC_SC_ID, SC_ID.get()),
            App.globalPut(CC_AC_ID, AC_ID.get()),
            App.globalPut(FC_P_ADDR, P_ADDR.get()),
            App.globalPut(FC_AMM_ID, AMM_ID.get()),
            App.globalPut(CC_claiming_period, claimPeriod.get()),
            App.globalPut(FC_MRAAL, minRewardAmountAddLiquid.get()),

            # Fetch start round for the pool from the SC
            #  Assert SC has a global state
            SC_glob_state,
            Assert(SC_glob_state.hasValue()),
            #  Assign 8 bytes starting at byte 32 as start round
            App.globalPut(CC_pool_start_round, Btoi(Extract(SC_glob_state.value(), Int(64), Int(8)))),
            # Fetch end round for the pool from the SC
            #  Assign 8 bytes starting at byte 40 as end round
            App.globalPut(CC_pool_end_round, Btoi(Extract(SC_glob_state.value(), Int(72), Int(8)))),
            # Fetch staking asset of the pool from the SC
            #  Assign 8 bytes starting at byte 16 as ASA ID
            App.globalPut(CC_S_ASA_ID, Btoi(Extract(SC_glob_state.value(), Int(48), Int(8)))),
            # Fetch reward asset of the pool from the SC
            #  Assign 8 bytes starting at byte 24 as ASA ID
            App.globalPut(FC_R_ASA_ID, Btoi(Extract(SC_glob_state.value(), Int(56), Int(8)))),

            # Initialize remaining global variables
            App.globalPut(CC_total_stake, Int(0)),
            App.globalPut(CC_last_compound_done, Int(LAST_COMPOUND_NOT_DONE)),
            App.globalPut(CC_last_compound_round, Int(0)),
            App.globalPut(CC_number_of_stakers, Int(0)),
            App.globalPut(CC_number_of_boxes, Int(0)),

            Approve()
        )

    @router.method(no_op=CallConfig.CALL)
    def on_setup():

        return Seq(
            # Assert sender is contract creator - only one that can setup the contract
            Assert(Txn.sender() == Global.creator_address()),
            # Assert last compounded round is zero - only at the start (i.e. setup can be done only once)
            Assert(App.globalGet(CC_last_compound_round) == Int(0)),

            # Assign start of pool as the last time compounding took place, thus it can't be done before it's meaningful
            App.globalPut(CC_last_compound_round, App.globalGet(CC_pool_start_round)),

            # Opt-in to S_ASA_ID
            InnerTxnBuilder.Execute(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: App.globalGet(CC_S_ASA_ID),
                    TxnField.asset_receiver: Global.current_application_address(),
                    TxnField.fee: Int(0),
                }
            ),

            # Opt-in to R_ASA_ID
            InnerTxnBuilder.Execute(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: App.globalGet(FC_R_ASA_ID),
                    TxnField.asset_receiver: Global.current_application_address(),
                    TxnField.fee: Int(0),
                }
            ),

            # Opt-in to SC_ID
            InnerTxnBuilder.Execute(
                {
                    TxnField.type_enum: TxnType.ApplicationCall,
                    TxnField.on_completion: OnComplete.OptIn,
                    TxnField.application_id: App.globalGet(CC_SC_ID),
                    TxnField.fee: Int(0),
                }
            ),

            # Approve the call
            Approve(),
        )

    @router.method(no_op=CallConfig.CALL)
    def trigger_compound():

        return Seq(
            # Compounding can be done only if enough time has passed since last compounding
            Assert(next_compound_round <= Global.round(), comment="Trigger compounding"),
            # Compounding does not make sense if the pool is not yet live - prevents also box creation prior to PSR
            Assert(Global.round() > App.globalGet(CC_pool_start_round), comment="Trigger compounding - pool live"),
            # Claim from SC and record the claiming in a box, without adding any additional stake. The fee is paid by CC
            claim_stake_record(Int(0), Int(PAY_FEE)),
            # Approve the call
            Approve(),
        )

    @router.method(no_op=CallConfig.CALL)
    def stake():

        # The request to stake must be accompanied by a payment transaction to deposit funds to cover the fees for at
        # least one compounding
        pay_txn_idx = Txn.group_index() - Int(2)
        # Amount for payment of compounding fees
        amt = Gtxn[pay_txn_idx].amount()

        # The request to stake must be accompanied by a transaction transferring the amount of S_ASA_ID to be staked
        xfer_txn_idx = Txn.group_index() - Int(1)
        # Amount of S_ASA_ID transferred to be staked
        amt_xfer = Gtxn[xfer_txn_idx].asset_amount()

        return Seq(
            # Deposits are allowed only if pool is still live
            Assert(Global.round() < App.globalGet(CC_pool_end_round)),

            # Staking is allowed only if user has either:
            #  claimed all compounding contributions (otherwise local contributions would not be correctly reflected) or
            #  user has currently a zero local stake, in which case the local number of boxes must be updated
            If(App.localGet(Txn.sender(), CC_local_number_of_boxes) == App.globalGet(CC_number_of_boxes)).Then(
                Assert(Int(1), comment="boxes up-to-date, user can stake")
            ).Else(
                If(BytesEq(App.localGet(Txn.sender(), CC_local_stake), LOCAL_STAKE_ZERO_BYTES)).Then(
                    Seq(
                        App.localPut(Txn.sender(), CC_local_number_of_boxes, App.globalGet(CC_number_of_boxes)),
                        Assert(Int(1), comment="user can stake since it has zero stake")
                    )
                ).Else(
                    Reject()
                )
            ),

            # The request to stake must be accompanied by a payment transaction to deposit funds to cover the fees for
            # at least one compounding
            #  Assert transaction is payment
            Assert(Gtxn[pay_txn_idx].type_enum() == TxnType.Payment),
            #  Assert transaction receiver is FC.address
            Assert(Gtxn[pay_txn_idx].receiver() == Global.current_application_address()),

            # The request to stake must be accompanied by a transaction transferring the amount to be staked
            #  Assert transaction is asset transfer
            Assert(Gtxn[xfer_txn_idx].type_enum() == TxnType.AssetTransfer),
            #  Assert transaction receiver is FC.address
            Assert(Gtxn[xfer_txn_idx].asset_receiver() == Global.current_application_address()),
            #  Assert transaction is transferring correct asset (redundant since opted-in only one asset, thus others
            #  would fail)
            Assert(Gtxn[xfer_txn_idx].xfer_asset() == App.globalGet(CC_S_ASA_ID)),

            # If request to stake is done when the pool is already live and a stake has already been deposited, it is
            # necessary to claim the amount first. For this claiming, the new staker needs to pay the fees, including
            # additional deposit for the newly created box while claiming.
            If(
                And(
                    Global.round() > App.globalGet(CC_pool_start_round),
                    App.globalGet(CC_total_stake) > Int(0)
                )
            ).Then(
                Seq(
                    # Assert the payment transferred is enough to cover the fees for this initial compounding due to
                    # staking plus for another trigger (at any later point)
                    Assert(amt >= Int(2 * FC_FEE_FOR_COMPOUND), comment="staking while pool live, stake already deposited"),
                    # Claim from SC and record the claiming in a box, while adding the newly deposited additional stake.
                    # Everything also get recorded in total stake.
                    claim_stake_record(amt_xfer, Int(PAY_FEE)),

                    # Local claim the results of this compounding (it is still with respect to user's old stake)
                    local_claim_box(App.globalGet(CC_number_of_boxes)),
                )
            ).Else(
                Seq(
                    # Assert the payment transferred is enough to cover the fees for the transfer to SC plus for a
                    # compound trigger (at any later point)
                    Assert(amt >= Int(FC_FEE_FOR_COMPOUND + STAKE_TO_SC_FEE)),
                    # Stake the deposited amount
                    stake_to_SC(amt_xfer, Int(PAY_FEE)),
                    # Update the total stake
                    App.globalPut(CC_total_stake, App.globalGet(CC_total_stake) + amt_xfer),
                )
            ),

            # Update the local stake
            App.localPut(
                Txn.sender(),
                CC_local_stake,
                BytesAdd(
                    App.localGet(Txn.sender(), CC_local_stake),
                    Concat(Itob(amt_xfer), BytesZero(Int(LOCAL_STAKE_N))),
                )
            ),

            # Approve the call
            Approve(),
        )

    @router.method(no_op=CallConfig.CALL)
    def compound_now():
        # To compound now, a payment transaction needs to deposit funds to cover the fees for the compounding
        pay_txn_idx = Txn.group_index() - Int(1)
        # Amount for payment of compounding fees
        amt = Gtxn[pay_txn_idx].amount()

        return Seq(
            # Makes sense to allow additional compounding only when the pool is live
            Assert(Global.round() < App.globalGet(CC_pool_end_round)),
            Assert(Global.round() > App.globalGet(CC_pool_start_round)),

            # The request to stake must be accompanied by a payment transaction to deposit funds to cover the fees for
            # the compounding
            #  Assert transaction is payment
            Assert(Gtxn[pay_txn_idx].type_enum() == TxnType.Payment),
            #  Assert transaction receiver is FC.address
            Assert(Gtxn[pay_txn_idx].receiver() == Global.current_application_address()),
            # Assert the payment transferred is enough to cover the fees for the compounding
            Assert(amt >= Int(FC_FEE_FOR_COMPOUND)),

            # Claim from SC and record the claiming in a box (do not add additional stake).
            claim_stake_record(Int(0), Int(PAY_FEE)),

            # Approve the call
            Approve(),
        )

    @router.method(no_op=CallConfig.CALL)
    def withdraw(amt: abi.Uint64, *, output: abi.Uint64) -> Expr:

        # The request to unstake must be accompanied by a payment transaction to deposit funds to cover the fees
        #  This could be optimized depending on when the unstaking is done, fees can be simply pooled.
        pay_txn_idx = Txn.group_index() - Int(1)
        # Amount for payment of fees
        amt_fee = Gtxn[pay_txn_idx].amount()

        # For storing user's local state at the start of the call (since it can increase due to claiming)
        local_stake_b = ScratchVar()
        # For storing amount which user actually gets withdraw - which can be higher than amt if another claiming has to
        # be done
        amt_b = ScratchVar()

        return Seq(
            # Withdrawals are allowed only if user has claimed all compounding contributions - otherwise one could lose
            # funds (i.e. give up the rewards)
            Assert(App.localGet(Txn.sender(), CC_local_number_of_boxes) == App.globalGet(CC_number_of_boxes)),

            # The request to unstake must be accompanied by a payment transaction to deposit funds to cover the fees
            #  Assert transaction is payment
            Assert(Gtxn[pay_txn_idx].type_enum() == TxnType.Payment),
            #  Assert transaction receiver is FC.address
            Assert(Gtxn[pay_txn_idx].receiver() == Global.current_application_address()),

            # Get user's local state (rounded down) - since it can increase due to claiming later on
            local_stake_b.store(floor_local_stake()),

            # Requested withdrawal can be at most up to the local stake
            Assert(amt.get() <= local_stake_b.load()),

            # Withdrawals are processed differently depending on when they are done
            If(Global.round() < App.globalGet(CC_pool_start_round)).Then(
                Seq(
                    # If pool has not yet started, there has been no compounding done so far, thus simply ustake the
                    # requested amount from SC
                    unstake_from_SC(amt.get(), Int(PAY_FEE)),
                    # That amount will be withdrawn
                    amt_b.store(amt.get()),
                    # Assert fees for the unstaking have been deposited
                    Assert(amt_fee >= Int(UNSTAKE_FROM_SC_FEE)),
                )
            ).Else(
                # If pool is still live
                If(Global.round() <= App.globalGet(CC_pool_end_round)).Then(
                    Seq(
                        # Claim from SC and record the claiming in a box, without adding any additional stake.
                        # Everything also get recorded in total stake.
                        claim_stake_record(Int(0), Int(PAY_FEE)),

                        # Local claim the results of this compounding
                        local_claim_box(App.globalGet(CC_number_of_boxes)),

                        # Unstake correct amount from SC
                        #  If withdraw amt equaled the whole local stake, interpret as a request to withdraw also the
                        #  effect of the last claim - which requires to call floor_local_stake() again for the unstaking
                        If(amt.get() == local_stake_b.load()).Then(
                            amt_b.store(floor_local_stake()),
                        ).Else(
                            amt_b.store(amt.get()),
                        ),
                        unstake_from_SC(amt_b.load(), Int(PAY_FEE)),

                        # Assert fees for the compounding and unstaking have been deposited
                        Assert(amt_fee >= Int(FC_FEE_FOR_COMPOUND + UNSTAKE_FROM_SC_FEE)),
                    )
                ).Else(
                    # If pool has already ended, a last compounding has to be done and all funds can be withdrawn from
                    # the pool to FC.address
                    If(App.globalGet(CC_last_compound_done) == Int(LAST_COMPOUND_NOT_DONE)).Then(
                        Seq(
                            # Claim from SC and record the claiming in a box, without adding any additional stake.
                            # Everything also get recorded in total stake.
                            claim_stake_record(Int(0), Int(PAY_FEE)),

                            # Local claim the results of this compounding
                            local_claim_box(App.globalGet(CC_number_of_boxes)),
                            #  If withdraw amt equaled the whole local stake, interpret as a request to withdraw also
                            #  the effect of the last claim - which requires to call floor_local_stake() again
                            If(amt.get() == local_stake_b.load()).Then(
                                amt_b.store(floor_local_stake()),
                            ).Else(
                                amt_b.store(amt.get()),
                            ),

                            # Unstake total stake from SC
                            unstake_from_SC(App.globalGet(CC_total_stake), Int(PAY_FEE)),

                            # Assert fees for the compounding and unstaking have been deposited
                            Assert(amt_fee >= Int(FC_FEE_FOR_COMPOUND + UNSTAKE_FROM_SC_FEE)),

                            # Mark that the last compounding has now been done
                            App.globalPut(CC_last_compound_done, Int(LAST_COMPOUND_DONE)),
                        )
                    )
                    .Else(
                        # If pool has already ended and a last compounding has already been done, stake can simply be
                        # withdrawn from FC.address since it’s already there.
                        # The amount to withdraw is simply the requested stake since no additional claiming happened
                        amt_b.store(amt.get())
                    )
                )
            ),

            # Send the requested amount (in case of a full withdrawal, also the possible last compounding) to the user.
            # Fees for this action are pooled by the user.
            sendAssetToSender(App.globalGet(CC_S_ASA_ID), amt_b.load()),

            # Record the new total stake
            App.globalPut(CC_total_stake, App.globalGet(CC_total_stake) - amt_b.load()),

            # Record that the new local stake for the user
            App.localPut(Txn.sender(), CC_local_stake, BytesMinus(
                    App.localGet(Txn.sender(), CC_local_stake),
                    Concat(Itob(amt_b.load()), BytesZero(Int(LOCAL_STAKE_N)))
                )
             ),

            # Output the withdrawn amount
            output.set(amt_b.load()),

            # Approve the call
            # Approve(), - leaving this in prevents outputting the results from the method because Approve() returns
            # sooner than the output.set returns
        )

    @router.method(no_op=CallConfig.CALL)
    def local_claim(up_to_box: abi.Uint64):
        # Make a local claim of the compounding contribution for each box from last claimed one (i.e.
        # local_number_of_boxes) up to (including) up_to_box.
        # All the boxes need to be provided in the box array call.

        idx = ScratchVar()
        init = idx.store(App.localGet(Txn.sender(), CC_local_number_of_boxes) + Int(1))
        cond = idx.load() <= up_to_box.get()
        iter = idx.store(idx.load() + Int(1))

        return Seq(
            # Process each supplied box
            For(init, cond, iter).Do(
                local_claim_box(idx.load())
            ),

            # Approve the call
            Approve(),
        )

    @router.method(no_op=CallConfig.CALL)
    def delete_boxes(down_to_box: abi.Uint64):
        # Delete each box from (including) number_of_boxes down to (excluding) down_to_box
        # All need to be supplied in the box array

        idx = ScratchVar()
        init = idx.store(App.globalGet(CC_number_of_boxes))
        cond = idx.load() > down_to_box.get()
        iter = idx.store(idx.load() - Int(1))

        return Seq(
            # Only app creator can delete boxes
            Assert(Txn.sender() == Global.creator_address()),
            # Boxes can be deleted only if there are no more accounts opted into the FC and the pool has ended, or the
            # claiming period has passed
            Assert(Or(
                And(App.globalGet(CC_number_of_stakers) == Int(0), Global.round() > App.globalGet(CC_pool_end_round)),
                Global.round() > App.globalGet(CC_pool_end_round) + App.globalGet(CC_claiming_period)
                )
            ),

            # Delete each supplied box
            For(init, cond, iter).Do(
                Assert(App.box_delete(Itob(idx.load()))),
            ),

            # Update new number of boxes
            App.globalPut(CC_number_of_boxes, idx.load()),

            # Approve the call
            Approve(),
        )

    return router


def compileFarmCompoundContract(algod_client):
    # Compile the program
    approval_program, clear_program, contract = getRouter().compile_program(version=8)

    with open("./compiled_files/FarmCompoundContract_approval.teal", "w") as f:
        f.write(approval_program)

    with open("./compiled_files/FarmCompoundContract_clear.teal", "w") as f:
        f.write(clear_program)

    with open("./compiled_files/FarmCompoundContract.json", "w") as f:
        import json

        f.write(json.dumps(contract.dictify()))

    # Compile program to binary
    approval_program_compiled = compile_program(algod_client, approval_program)
    # Compile program to binary
    clear_state_program_compiled = compile_program(algod_client, clear_program)

    approval_program_compiled_b64 = compile_program_b64(algod_client, approval_program)
    ExtraProgramPages = math.ceil(len(base64.b64decode(approval_program_compiled_b64)) / 2048) - 1

    return [approval_program_compiled, clear_state_program_compiled,
            ExtraProgramPages, contract]
