use crate::*;
use anchor_lang::solana_program::{instruction::Instruction, program::invoke};

// LST Unstake Arbitrage (Logic 2)
#[derive(AnchorSerialize, AnchorDeserialize)]
pub struct LstArbitrageData {
    pub lst_mint: Pubkey,
    pub protocol_router: Pubkey, // Sanctum router or Marinade state
    pub jupiter_swap_ix: InstructionData, // Jupiter SOL -> LST swap
    pub unstake_ix: InstructionData, // Protocol unstake instruction
}

pub fn lst_unstake_arbitrage(
    ctx: &Context<ExecuteArbitrage>,
    data: &[u8],
) -> Result<()> {
    let arb_data: LstArbitrageData = AnchorDeserialize::deserialize(&mut &data[..])?;

    // Step 1: Jupiter swap SOL -> LST using borrowed SOL
    let jupiter_ix = Instruction {
        program_id: arb_data.jupiter_swap_ix.program_id,
        accounts: arb_data.jupiter_swap_ix.accounts.into_iter().map(|meta| {
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: meta.pubkey,
                is_signer: meta.is_signer,
                is_writable: meta.is_writable,
            }
        }).collect(),
        data: arb_data.jupiter_swap_ix.data,
    };

    invoke(&jupiter_ix, ctx.remaining_accounts)?;

    // Step 2: CPI to protocol unstake (Sanctum/Marinade)
    let unstake_ix = Instruction {
        program_id: arb_data.unstake_ix.program_id,
        accounts: arb_data.unstake_ix.accounts.into_iter().map(|meta| {
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: meta.pubkey,
                is_signer: meta.is_signer,
                is_writable: meta.is_writable,
            }
        }).collect(),
        data: arb_data.unstake_ix.data,
    };

    invoke(&unstake_ix, ctx.remaining_accounts)?;

    // The repay will happen automatically in the main function
    msg!("LST unstake arbitrage executed successfully");
    Ok(())
}