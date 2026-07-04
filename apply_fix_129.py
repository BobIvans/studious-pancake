import os

def apply_fix_129():
    target_file = "src/ingest/helius_webhook_handler.py"
    if not os.path.exists(target_file):
        print(f"❌ Файл не найден: {target_file}")
        return

    with open(target_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if fix is already applied
    if "FIX 129: Handle GRADUATION events" in content:
        print("✅ Фикс #129 уже применен.")
        return

    # Add GRADUATION and TRANSFER handlers in _process_event
    target_block = """                        await self.opportunity_callback(opportunity, webhook_id)

        except Exception as e:
            logger.error(f"Event processing error: {e}")"""

    replacement_block = """                        await self.opportunity_callback(opportunity, webhook_id)

            # FIX 129: Handle GRADUATION events
            elif event_type == 'GRADUATION':
                opportunity = self._parse_graduation_event(event)
                if opportunity:
                    metadata = {
                        'webhook_source': 'helius',
                        'event_type': 'GRADUATION',
                        'slot': event.get('slot'),
                        'timestamp': event.get('timestamp')
                    }
                    await self.data_aggregator.log_opportunity_found(webhook_id, opportunity, metadata)
                    if self.opportunity_callback:
                        await self.opportunity_callback(opportunity, webhook_id)

            # FIX 129: Handle TRANSFER events
            elif event_type == 'TRANSFER':
                opportunity = self._parse_transfer_event(event)
                if opportunity:
                    metadata = {
                        'webhook_source': 'helius',
                        'event_type': 'TRANSFER',
                        'slot': event.get('slot'),
                        'timestamp': event.get('timestamp')
                    }
                    await self.data_aggregator.log_opportunity_found(webhook_id, opportunity, metadata)
                    if self.opportunity_callback:
                        await self.opportunity_callback(opportunity, webhook_id)
                    if self.webhook_queue:
                        try:
                            await self.webhook_queue.put(opportunity)
                        except asyncio.QueueFull:
                            pass

        except Exception as e:
            logger.error(f"Event processing error: {e}")"""

    # Add new methods at the end of the class
    class_end = """        if analysis['multiple_lst_involved']:
            analysis['recommended_scan_tokens'].extend(opportunity.get('tokens_involved', []))
        return analysis"""

    class_end_replacement = """        if analysis['multiple_lst_involved']:
            analysis['recommended_scan_tokens'].extend(opportunity.get('tokens_involved', []))
        return analysis

    # FIX 129: Helper method for parsing Graduation events
    def _parse_graduation_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            token_transfers = event.get('tokenTransfers', [])
            token_mint = token_transfers[0].get('mint') if token_transfers else None
            account_data = event.get('accountData', [])
            raydium_pool = account_data[0].get('account') if account_data else None

            if not token_mint:
                return None

            return {
                'strategy': 'graduation',
                'type': 'token_graduation',
                'token_pair': ('SOL', token_mint),
                'token_mint': token_mint,
                'raydium_pool': raydium_pool,
                'trigger_data': {
                    'platform': 'pump_fun' if '39azUYFW' in str(event) else 'moonshot',
                    'token_mint': token_mint,
                    'raydium_pool': raydium_pool,
                    'timestamp': event.get('timestamp', time.time())
                },
                'expected_profit_sol': 0.005,
                'description': f"Token graduation detected: {token_mint[:8]}"
            }
        except Exception as e:
            logger.error(f"Error parsing graduation event: {e}")
            return None

    # FIX 129: Helper method for parsing TRANSFER events (detect depeg signals)
    def _parse_transfer_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            token_transfers = event.get('tokenTransfers', [])
            if not token_transfers:
                return None

            transfer_data = token_transfers[0]
            mint = transfer_data.get('mint')
            amount = float(transfer_data.get('tokenAmount', 0))

            if mint in WebhookConfig.LST_ADDRESSES and amount > 10000:
                return {
                    'strategy': 'lst_depeg',
                    'type': 'large_transfer_signal',
                    'token_mint': mint,
                    'amount': amount,
                    'trigger_immediate_scan': True,
                    'description': f"Large transfer: {amount:.2f} of {mint[:8]}... (triggering scan)"
                }
        except Exception as e:
            logger.error(f"Error parsing transfer event: {e}")
        return None"""

    modified = False
    if target_block in content:
        content = content.replace(target_block, replacement_block)
        modified = True
        print("✅ Добавлены обработчики GRADUATION и TRANSFER в _process_event")

    if class_end in content:
        content = content.replace(class_end, class_end_replacement)
        modified = True
        print("✅ Добавлены методы _parse_graduation_event и _parse_transfer_event")

    if modified:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)
        print("✅ Успешно применен фикс #129: TRANSFER и GRADUATION события теперь обрабатываются.")
    else:
        print("⚠️ Фикс #129 не был применен (возможно, уже существует или структура файла изменилась)")

if __name__ == "__main__":
    apply_fix_129()