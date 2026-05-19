use crate::*;
use anchor_lang::solana_program::{instruction::Instruction, program::invoke};

// Phoenix vs AMM Arbitrage (Logic 4)
#[derive(AnchorSerialize, AnchorDeserialize)]
pub struct OrderbookArbitrageData {
    pub phoenix_market: Pubkey,
    pub token_mint: Pubkey,
    pub phoenix_fill_ix: InstructionData, // Phoenix fill order instruction
    pub raydium_swap_ix: InstructionData, // Raydium swap instruction
}

pub fn phoenix_vs_amm(
    ctx: &Context<ExecuteArbitrage>,
    data: &[u8],
) -> Result<()> {
    let arb_data: OrderbookArbitrageData = AnchorDeserialize::deserialize(&mut &data[..])?;

    // Step 1: Fill Phoenix orderbook orders (buy cheap from orderbook)
    let phoenix_ix = Instruction {
        program_id: arb_data.phoenix_fill_ix.program_id,
        accounts: arb_data.phoenix_fill_ix.accounts.into_iter().map(|meta| {
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: meta.pubkey,
                is_signer: meta.is_signer,
                is_writable: meta.is_writable,
            }
        }).collect(),
        data: arb_data.phoenix_fill_ix.data,
    };

    invoke(&phoenix_ix, ctx.remaining_accounts)?;

    // Step 2: Sell to Raydium AMM for profit
    let raydium_ix = Instruction {
        program_id: arb_data.raydium_swap_ix.program_id,
        accounts: arb_data.raydium_swap_ix.accounts.into_iter().map(|meta| {
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: meta.pubkey,
                is_signer: meta.is_signer,
                is_writable: meta.is_writable,
            }
        }).collect(),
        data: arb_data.raydium_swap_ix.data,
    };

    invoke(&raydium_ix, ctx.remaining_accounts)?;

    msg!("Phoenix vs AMM arbitrage executed successfully");
    Ok(())
}