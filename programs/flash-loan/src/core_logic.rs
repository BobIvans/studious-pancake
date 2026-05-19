use crate::*;
use anchor_lang::solana_program::{instruction::Instruction, program::invoke};

pub fn borrow_from_marginfi(
    ctx: &Context<ExecuteArbitrage>,
    base_mint: Pubkey,
    amount: u64,
) -> Result<()> {
    // CPI to MarginFi borrow using instruction discriminator
    let borrow_discriminator = [145u8, 89, 235, 97, 24, 52, 165, 215];

    let mut data = borrow_discriminator.to_vec();
    data.extend_from_slice(&amount.to_le_bytes());

    let borrow_ix = Instruction {
        program_id: MARGINFI_PROGRAM_ID,
        accounts: vec![
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.marginfi_bank.key(),
                is_signer: false,
                is_writable: true,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.marginfi_account.key(),
                is_signer: false,
                is_writable: true,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.signer.key(),
                is_signer: true,
                is_writable: true,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.marginfi_group.key(),
                is_signer: false,
                is_writable: false,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.user_token_account.key(),
                is_signer: false,
                is_writable: true,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: anchor_spl::token::ID,
                is_signer: false,
                is_writable: false,
            },
        ],
        data,
    };

    invoke(&borrow_ix, &[
        ctx.accounts.marginfi_bank.to_account_info(),
        ctx.accounts.marginfi_account.to_account_info(),
        ctx.accounts.signer.to_account_info(),
        ctx.accounts.marginfi_group.to_account_info(),
        ctx.accounts.user_token_account.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
    ])?;

    msg!("Borrowed {} tokens from MarginFi", amount);
    Ok(())
}

pub fn repay_to_marginfi(
    ctx: &Context<ExecuteArbitrage>,
    base_mint: Pubkey,
    amount: u64,
) -> Result<()> {
    // CPI to MarginFi repay using instruction discriminator
    let repay_discriminator = [49u8, 96, 69, 171, 120, 51, 165, 154];

    let mut data = repay_discriminator.to_vec();
    data.extend_from_slice(&amount.to_le_bytes());

    let repay_ix = Instruction {
        program_id: MARGINFI_PROGRAM_ID,
        accounts: vec![
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.marginfi_bank.key(),
                is_signer: false,
                is_writable: true,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.marginfi_account.key(),
                is_signer: false,
                is_writable: true,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.signer.key(),
                is_signer: true,
                is_writable: true,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.marginfi_group.key(),
                is_signer: false,
                is_writable: false,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: ctx.accounts.user_token_account.key(),
                is_signer: false,
                is_writable: true,
            },
            anchor_lang::solana_program::instruction::AccountMeta {
                pubkey: anchor_spl::token::ID,
                is_signer: false,
                is_writable: false,
            },
        ],
        data,
    };

    invoke(&repay_ix, &[
        ctx.accounts.marginfi_bank.to_account_info(),
        ctx.accounts.marginfi_account.to_account_info(),
        ctx.accounts.signer.to_account_info(),
        ctx.accounts.marginfi_group.to_account_info(),
        ctx.accounts.user_token_account.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
    ])?;

    msg!("Repaid {} tokens to MarginFi", amount);
    Ok(())
}

pub fn dex_to_dex_arbitrage(
    ctx: &Context<ExecuteArbitrage>,
    data: &[u8],
) -> Result<()> {
    // Decode arbitrage data and execute Jupiter routes
    let arb_data: ArbitrageData = AnchorDeserialize::deserialize(&mut &data[..])?;
    for ix_data in arb_data.instructions {
        let ix = Instruction {
            program_id: ix_data.program_id,
            accounts: ix_data.accounts.into_iter().map(|meta| AccountMeta {
                pubkey: meta.pubkey,
                is_signer: meta.is_signer,
                is_writable: meta.is_writable,
            }).collect(),
            data: ix_data.data,
        };
        // Invoke via CPI
        invoke(&ix, ctx.remaining_accounts)?;
    }
    msg!("DEX-to-DEX arbitrage executed");
    Ok(())
}