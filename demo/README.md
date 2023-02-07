# Video Demo

The video excerpts below demonstrate an example scenario of interactions of four accounts `a`, `b`, `c`, and `d` 
with the autocompounder for a liquidity farming pool.
The interactions are made with the provided interaction [script](../interactions_state_machine.py) and take place on 
Algorand Testnet.

Before the start of interactions with the autocompounder, a liquidity farming pool is first created on 
[Cometa](https://app.testnet.cometa.farm/farm) for farming of ALGO-USDC pair of 
[Tinyman](https://testnet.tinyman.org/#/pool/UDFWT5DW3X5RZQYXKQEMZ6MRWAEYHWYP7YUAPZKPW6WJK3JH3OZPL7PO2Y) V2 AMM 
liquidity pool (deployed App ID [157582406](https://testnet.algoexplorer.io/application/157582406)).
The farming rewards are paid in [test USDC](https://testnet.algoexplorer.io/asset/10458941).
The accounts also deposit funds to the AMM liquidity pool and acquire the corresponding
[token](https://testnet.algoexplorer.io/asset/148620458) that can be staked in the created staking pool. 

![Video of liquidity farming pool creation on Cometa and acquiring staking token by depositing funds to Tinyman V2 AMM](https://user-images.githubusercontent.com/115161770/217259043-8cf967a6-fe4f-4184-842a-441ce03b40c1.mp4)

When running the interaction script, [REST endpoints](https://developer.algorand.org/docs/rest-apis/restendpoints/) for 
Algorand protocol daemon first need to be entered.
Connections via Sandbox to the Algorand Testnet are established.
Then, account `a` creates the autocompounder, sets its parameters and sets up the contract 
(deployed App ID [157582655](https://testnet.algoexplorer.io/application/157582655)).

![Video of user (a) creating and setting up the autocompounder contract](https://user-images.githubusercontent.com/115161770/217259832-fcd47db8-e92c-451c-8626-0bff41c4326e.mp4)

Afterwards, account `a` switches to normal user interaction mode, opts into the contract, and deposits staking tokens 
as well as funds for one compounding.
Thereafter, account `b` connects to the autocompounder and does the same.

![Video of users (a) and (b) opt-ing into the contract and staking](https://user-images.githubusercontent.com/115161770/217259810-7569042a-4e1e-418b-93f9-ed4a88f4cf2b.mp4)

Account `b` withdraws part of its deposited stake.
No compounding takes place because the pool hasn't gone live yet.

![Video of user (b) withdrawing funds while the pool hasn't gone live yet](https://user-images.githubusercontent.com/115161770/217259780-63ac3a54-8bb8-48a1-90b1-59abb79616df.mp4)

When the pool is already live, account `c` opts into the autocompounder and stakes its tokens.
Since the pool is now live, the stake is first compounded.
This action results in a rescheduling of the autocompounder's schedule.

![Video of user (c) opt-ing into the contract and staking](https://user-images.githubusercontent.com/115161770/217259755-ea861d11-9ef1-4860-a820-3d3dd9006af5.mp4)

Account `c` stakes additional tokens.
Again, the stake first needs to be compounded.
This action again results in a rescheduling of the autocompounder's schedule.

![Video of user (c) staking additional tokens](https://user-images.githubusercontent.com/115161770/217260010-cffe144a-16f6-4dce-8ab6-eaadce53af7c.mp4)

Account `b` withdraws some tokens.
Before that can be done, it needs to "locally claim" the interest from the previous compounding actions.
Afterwards, the stake is withdrawn, which again requires additional compounding since the pool is live.

![Video of user (b) withdrawing some tokens while the pool is live](https://user-images.githubusercontent.com/115161770/217260070-53b22779-2abe-412f-af69-105e1d5f4b68.mp4)

Account `d` connects to the platform.
It triggers the compounding according to the schedule without having to be opted-into the contract or paying any 
compounding fees.
Afterwards, it issues an instant additional compounding of the stake.

![Video of user (d) triggeting a scheduled compounding and additional instant compounding](https://user-images.githubusercontent.com/115161770/217260126-f7afd2eb-508e-463c-9cf2-7a7c0fe1c2d1.mp4)

*Note: Despite only three users depositing funds for future compoundings, there can be more than three compounding 
triggers because the required deposit funds assume a maximum size for the created box. In reality, the boxes are smaller
in the majority of cases, thus more funds are available for compounding.* 

The pool ends.
Account `b` connects to the platform and withdraws all its stake and opts out of the contract.
Account `c` and `a` do the same.

![Video of users (a), (b) and (c) withdrawing funds after the pool ends](https://user-images.githubusercontent.com/115161770/217260619-9e8f9c5d-377a-4796-9581-f7cc9ac24da5.mp4)

Account `a` deletes the boxes that were created.
This is possible despite the claiming period not yet being finished because there are no more accounts opted into the
contract.
Afterwards, it deletes the contract, receiving the remaining funds from it.

![Video of user (a) deleting the boxes and contract after the pool ends](https://user-images.githubusercontent.com/115161770/217260339-3bb0bb63-062a-4cd2-b14d-c4134c552fbf.mp4)
