use anchor_lang::prelude::*;
use anchor_lang::solana_program::{instruction::Instruction, program::invoke, pubkey::Pubkey};
use anchor_spl::token;

// Core constants
pub const MARGINFI_PROGRAM_ID: Pubkey = pubkey!("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA");
pub const JUPITER_PROGRAM_ID: Pubkey = pubkey!("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
pub const SOL_MINT: Pubkey = pubkey!("So11111111111111111111111111111111111111112");

// BLUE OCEAN STRATEGIES (Monopoly, Deterministic Profits)
// Strategy modules
pub mod core_logic; // Atomic MarginFi wrapper (Logic 1)
pub mod lst_arbitrage; // LST unstake arbitrage (Logic 2) - BLUE OCEAN
// pub mod liquidation_arbitrage; // Kamino flash liquidations (Logic 3) - RED OCEAN FROZEN
pub mod orderbook_arbitrage; // Phoenix vs AMM (Logic 4) - BLUE OCEAN
pub mod sniping_arbitrage; // Pump.fun migration sniping (Logic 5) - BLUE OCEAN

#[program]
pub mod flash_loan {
    use super::*;

    // Unified entry point for all arbitrage strategies
    pub fn execute_arbitrage(
        ctx: Context<ExecuteArbitrage>,
        strategy_type: u8, // BLUE OCEAN: 2=LST Unstake, 4=Orderbook-AMM, 5=Pump.fun Sniping | RED OCEAN (FROZEN): 1=DEX-DEX, 3=Kamino Liquidations
        base_mint: Pubkey,
        borrow_amount: u64,
        expected_min_return: u64, // Slippage checkpoint
        strategy_data: Vec<u8>, // Encoded strategy-specific data
    ) -> Result<()> {
        let initial_balance = ctx.accounts.signer.lamports();

        // Execute MarginFi borrow (Core Logic 1)
        core_logic::borrow_from_marginfi(
            &ctx,
            base_mint,
            borrow_amount,
        )?;

        // Execute Blue Ocean strategy-specific arbitrage (frozen Red Ocean strategies)
        match strategy_type {
            // 1 => DEX-to-DEX arbitrage (FROZEN: Red Ocean - too competitive)
            2 => lst_arbitrage::lst_unstake_arbitrage(&ctx, &strategy_data)?, // SOL/LST protocols (Blue Ocean)
            // 3 => Kamino liquidations (FROZEN: Institutional competition)
            4 => orderbook_arbitrage::phoenix_vs_amm(&ctx, &strategy_data)?, // Phoenix CLOB vs AMM (Blue Ocean)
            5 => sniping_arbitrage::pump_fun_sniping(&ctx, &strategy_data)?, // Pump.fun migrations (Blue Ocean)
            _ => return err!(ErrorCode::UnsupportedStrategy),
        }

        // Execute MarginFi repay (Core Logic 1)
        core_logic::repay_to_marginfi(
            &ctx,
            base_mint,
            borrow_amount,
        )?;

        // Phase 29: Removed close_account logic. ATA management is handled by backend.


        // Slippage checkpoint: Verify minimum return
        let final_balance = ctx.accounts.signer.lamports();
        let profit = final_balance.saturating_sub(initial_balance);

        // Iron-clad profit guarantee: transaction reverts if negative profit
        require!(final_balance > initial_balance, ErrorCode::NegativeProfit);

        require!(profit >= expected_min_return, ErrorCode::SlippageExceeded);

        msg!("Arbitrage completed: strategy={}, profit={} lamports", strategy_type, profit);
        Ok(())
    }

    // Phase 28: Lightweight Profit Guard (No CPI)
    pub fn verify_profit(
        ctx: Context<VerifyProfit>,
        base_mint: Pubkey,
        expected_min_return: u64,
    ) -> Result<()> {
        // Phase 28: Check the token account balance (works for wSOL and SPL tokens)
        let current_balance = ctx.accounts.user_token_account.amount;

        require!(current_balance >= expected_min_return, ErrorCode::NegativeProfit);
        msg!("Profit verified: base_mint={} current_balance={} expected_min_return={}", base_mint, current_balance, expected_min_return);
        Ok(())
    }
}

// Data structures
#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct ArbitrageData {
    pub instructions: Vec<InstructionData>,
    pub accounts: Vec<Pubkey>, // Additional accounts for CPI
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct InstructionData {
    pub program_id: Pubkey,
    pub accounts: Vec<AccountMetaData>,
    pub data: Vec<u8>,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct AccountMetaData {
    pub pubkey: Pubkey,
    pub is_signer: bool,
    pub is_writable: bool,
}

#[derive(Accounts)]
#[instruction(base_mint: Pubkey, expected_min_return: u64)]
pub struct VerifyProfit<'info> {
    #[account(mut)]
    pub signer: Signer<'info>,
    #[account(
        constraint = user_token_account.owner == signer.key()
    )]
    pub user_token_account: Account<'info, token::TokenAccount>,
}

#[derive(Accounts)]
#[instruction(strategy_type: u8, base_mint: Pubkey, borrow_amount: u64, expected_min_return: u64, strategy_data: Vec<u8>)]
pub struct ExecuteArbitrage<'info> {
    #[account(mut)]
    pub signer: Signer<'info>,

    // MarginFi core accounts
    #[account(mut)]
    pub marginfi_group: AccountInfo<'info>,
    #[account(mut)]
    pub marginfi_account: AccountInfo<'info>,
    #[account(mut)]
    pub marginfi_bank: AccountInfo<'info>,
    #[account(mut)]
    pub user_token_account: AccountInfo<'info>,

    pub token_program: Program<'info, anchor_spl::token>,
    pub system_program: Program<'info, System>,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Unsupported arbitrage strategy")]
    UnsupportedStrategy,
    #[msg("Slippage exceeded expected minimum return")]
    SlippageExceeded,
    #[msg("Negative profit - transaction should revert")]
    NegativeProfit,
}