from pyteal import *
# ----- ----- -----    Constants     ----- ----- -----

# How many rounds to wait for a transaction approval after submission
TX_APPROVAL_WAIT = 3

# ----- -----    General     ----- -----
LAST_COMPOUND_NOT_DONE = 0
LAST_COMPOUND_DONE = 1

# QM.N
LOCAL_STAKE_M = 8
LOCAL_STAKE_N = 8
LOCAL_STAKE_SIZE = LOCAL_STAKE_M + LOCAL_STAKE_N
LOCAL_STAKE_ZERO_BYTES = BytesZero(Int(LOCAL_STAKE_SIZE))

# Number of bytes needed for the box name
BOX_NAME_SIZE = 8
# Maximum number of bytes needed for the box
BOX_MAX_SIZE = LOCAL_STAKE_SIZE

MIN_TX_FEE = 1_000
STAKE_TO_SC_FEE = 3 * MIN_TX_FEE
UNSTAKE_FROM_SC_FEE = 3 * MIN_TX_FEE
CLAIM_FROM_SC_FEE = 4 * MIN_TX_FEE
BOX_FEE = 2_500 + 400*(BOX_NAME_SIZE+BOX_MAX_SIZE)
ZAP_FEE = 4 * MIN_TX_FEE

PAY_FEE = 1
DO_NOT_PAY_FEE = 0

# ----- -----    Compound Contract     ----- -----
# Fees for one trigger = fee for box + fee for claiming from SC + fee for staking to SC
CC_FEE_FOR_COMPOUND = BOX_FEE + CLAIM_FROM_SC_FEE + STAKE_TO_SC_FEE

# ----- Global variables  -----
# Number of global variables
CC_NUM_GLOBAL_UINT = 11
CC_NUM_GLOBAL_BYTES = 0

# Total Stake: deposited by all users (accumulated through compounding)
CC_total_stake = Bytes("TS")

# Pool End Round: round number of when the staking pool ends
CC_pool_end_round = Bytes("PER")

# Pool Start Round: round number of when the staking pool starts
CC_pool_start_round = Bytes("PSR")

# Last Compound Done: set to LAST_COMPOUND_DONE when the pool has been compounded after the pool has ended, and thus it
# is not necessary to continue compounding
CC_last_compound_done = Bytes("LCD")

# Last Compound Round: round number of when the stake has been last compounded
CC_last_compound_round = Bytes("LCR")

# Number of Stakers
CC_number_of_stakers = Bytes("NS")

# Claiming Period: number of rounds after the pool has ended that creator has to wait before the contract can be deleted
# i.e. the number of rounds users have to withdraw their stakes and rewards
CC_claiming_period = Bytes("CP")

# Number of Boxes: number of boxes created by the contract
CC_number_of_boxes = Bytes("NB")

# Staking Contract ID: ID of the staking pool to compound
CC_SC_ID = Bytes("SC_ID")

# Associated Contract ID: app ID with which SC interacts
CC_AC_ID = Bytes("AC_ID")

# S_ASA ID: ID of the staking asset
CC_S_ASA_ID = Bytes("S_ASA_ID")


# -----  Local variables  -----

# Number of global variables
CC_NUM_LOCAL_UINT = 1
CC_NUM_LOCAL_BYTES = 1

# Local Number of Boxes: Number of box when the user has last compounded their rewards
CC_local_number_of_boxes = Bytes("LNB")

# Local Stake: amount staked by the users (accumulated through compounding) - a fractional number!
CC_local_stake = Bytes("LS")


# ----- ----- -----                ----- ----- -----

# ----- -----    Farm Compound Contract     ----- -----
# Fees for one trigger = fee for box + fee for claiming from SC + fee for single-sided liquidity addition +
# fee for staking to SC
FC_FEE_FOR_COMPOUND = BOX_FEE + CLAIM_FROM_SC_FEE + ZAP_FEE + STAKE_TO_SC_FEE

# ----- Global variables  -----
# Same as for normal Compound Contract and the additional ones below

# Number of global variables
FC_NUM_GLOBAL_UINT = CC_NUM_GLOBAL_UINT + 3
FC_NUM_GLOBAL_BYTES = CC_NUM_GLOBAL_BYTES + 1

# R_ASA ID: ID of the reward asset
FC_R_ASA_ID = Bytes("R_ASA_ID")

# AMM ID: ID of the AMM contract which issues the farming token
FC_AMM_ID = Bytes("AMM_ID")

# Pool address belonging to AMM ID and farming token
FC_P_ADDR = Bytes("P_ADDR")

# Minimum Reward Amount Add Liquidity: the minimum amount of R_ASA_ID that is needed to be added to the farming pool
# P_ADDR of AMM_ID
FC_MRAAL = Bytes("MRAAL")

# -----  Local variables  -----
# Same as for normal Compound Contract
FC_NUM_LOCAL_UINT = CC_NUM_LOCAL_UINT
FC_NUM_LOCAL_BYTES = CC_NUM_LOCAL_BYTES

# ----- ----- -----                ----- ----- -----

CC_approval_program = None
CC_clear_state_program = None
CC_ExtraProgramPages = None
CC_contract = None

FC_approval_program = None
FC_clear_state_program = None
FC_ExtraProgramPages = None
FC_contract = None

def init_global_vars(algod_client):
    # Get info about CompoundContract
    import src.CompoundContract as CC
    global CC_approval_program, CC_clear_state_program, CC_ExtraProgramPages, CC_contract
    [CC_approval_program, CC_clear_state_program, CC_ExtraProgramPages, CC_contract] = \
        CC.compileCompoundContract(algod_client)

    # Get info about FarmCompoundContract
    import src.FarmCompoundContract as FC
    global FC_approval_program, FC_clear_state_program, FC_ExtraProgramPages, FC_contract
    [FC_approval_program, FC_clear_state_program, FC_ExtraProgramPages, FC_contract] = \
        FC.compileFarmCompoundContract(algod_client)
