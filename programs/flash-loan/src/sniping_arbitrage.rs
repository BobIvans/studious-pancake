use crate::*;
use anchor_lang::solana_program::{instruction::Instruction, program::invoke};

// Pump.fun Migration Sniping (Logic 5)
#[derive(AnchorSerialize, AnchorDeserialize)]
pub struct SnipingArbitrageData {
    pub pump_fun_token: Pubkey,
    pub migration_ix: InstructionData, // Pump.fun migration instruction
    pub buy_ix: InstructionData, // Jupiter or Raydium buy instruction
}

pub fn pump_fun_sniping(
    ctx: &Context<ExecuteArbitrage>,
    data: &[u8],
) -> Result<()> {
    let arb_data: SnipingArbitrageData = AnchorDeserialize::deserialize(&mut &data[..])?;

    // Step 1: Execute Pump.fun migration (if needed)
    let migration_ix = Instruction {
        program_id: arb_data.migration_ix.program_id,
        accounts: arb_data.migration_ix.accounts.into_iter().map(|meta| {
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: meta.pubkey,
                is_signer: meta.is_signer,
                is_writable: meta.is_writable,
            }
        }).collect(),
        data: arb_data.migration_ix.data,
    };

    invoke(&migration_ix, ctx.remaining_accounts)?;

    // Step 2: Buy the token immediately after migration
    let buy_ix = Instruction {
        program_id: arb_data.buy_ix.program_id,
        accounts: arb_data.buy_ix.accounts.into_iter().map(|meta| {
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: meta.pubkey,
                is_signer: meta.is_signer,
                is_writable: meta.is_writable,
            }
        }).collect(),
        data: arb_data.buy_ix.data,
    };

    invoke(&buy_ix, ctx.remaining_accounts)?;

    msg!("Pump.fun sniping arbitrage executed successfully");
    Ok(())
}