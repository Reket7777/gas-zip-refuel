import json
import time
import random
from web3 import Web3
from eth_account import Account
import requests
from typing import List, Dict
import logging
from simple_term_menu import TerminalMenu

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('refuel.log'),
        logging.StreamHandler()
    ]
)

class ChainInfo:
    CHAINS = {
        1: {"name": "Ethereum", "rpc": "https://eth.llamarpc.com"},
        10: {"name": "Optimism", "rpc": "https://mainnet.optimism.io"},
        42161: {"name": "Arbitrum", "rpc": "https://arb1.arbitrum.io/rpc"},
        43114: {"name": "Avalanche", "rpc": "https://api.avax.network/ext/bc/C/rpc"},
        8453: {"name": "Base", "rpc": "https://mainnet.base.org"},
        56: {"name": "BSC", "rpc": "https://bsc-dataseed.binance.org"},
        137: {"name": "Polygon", "rpc": "https://polygon-rpc.com"},
        534352: {"name": "Scroll", "rpc": "https://rpc.scroll.io"},
        59144: {"name": "Linea", "rpc": "https://rpc.linea.build"},
        81457: {"name": "Blast", "rpc": "https://blast.blockpi.network/v1/rpc/public"},
        324: {"name": "zkSync", "rpc": "https://mainnet.era.zksync.io"},
        1625: {"name": "Gravity", "rpc": "https://gravitychain.io/rpc"},
        100: {"name": "Gnosis", "rpc": "https://rpc.gnosis.gateway.fm"},
        10143: {"name": "Monad Testnet", "rpc": "https://testnet-rpc.monad.xyz"}
        # Add more chains as needed
    }

    @classmethod
    def get_chain_options(cls) -> List[str]:
        return [f"{chain_id} - {info['name']}" for chain_id, info in cls.CHAINS.items()]

    @classmethod
    def get_chain_id(cls, selection: str) -> int:
        return int(selection.split(" - ")[0])

    @classmethod
    def get_rpc(cls, chain_id: int) -> str:
        return cls.CHAINS[chain_id]["rpc"]

class AutoRefuel:
    def __init__(self):
        self.load_private_keys()
        self.gas_contract = "0x391E7C679d29bD940d63be94AD22A25d25b5A604"
        self.setup_settings()
        
    def load_private_keys(self):
        try:
            with open('pk.txt', 'r') as f:
                self.private_keys = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            logging.error("pk.txt not found")
            raise

    def setup_settings(self):
        print("\n=== Gas.zip Refuel Configuration ===")
        
        # Amount settings
        print("\nAmount Settings:")
        use_random = input("Use random amount? (y/n): ").lower() == 'y'
        if use_random:
            min_amount = float(input("Enter minimum amount (e.g., 0.001): "))
            max_amount = float(input("Enter maximum amount (e.g., 0.002): "))
            fixed_amount = 0
        else:
            min_amount = max_amount = 0
            fixed_amount = float(input("Enter fixed amount (e.g., 0.001): "))

        # Chain selection
        print("\nSelect source chain:")
        chain_options = ChainInfo.get_chain_options()
        terminal_menu = TerminalMenu(chain_options)
        from_chain_index = terminal_menu.show()
        from_chain_selection = chain_options[from_chain_index]
        from_chain_id = ChainInfo.get_chain_id(from_chain_selection)
        
        print("\nSelect destination chains (space to select, enter to confirm):")
        terminal_menu = TerminalMenu(
            chain_options,
            multi_select=True,
            show_multi_select_hint=True
        )
        to_chain_indices = terminal_menu.show()
        to_chain_ids = [ChainInfo.get_chain_id(chain_options[i]) for i in to_chain_indices]

        self.settings = {
            "use_random_amount": use_random,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "fixed_amount": fixed_amount,
            "gas_multiplier": 1.1,
            "max_gas_price": 30,
            "min_delay": 30,
            "max_delay": 60,
            "wait_for_confirmation": True,
            "refuel_configs": [{
                "from_chain_id": from_chain_id,
                "from_chain_rpc": ChainInfo.get_rpc(from_chain_id),
                "to_chain_ids": to_chain_ids
            }]
        }

    def get_random_amount(self, min_amount: float, max_amount: float) -> int:
        amount = random.uniform(min_amount, max_amount)
        return Web3.to_wei(amount, 'ether')

    def get_calldata(self, from_chain: int, amount_wei: int, to_chains: List[int], from_address: str, to_address: str) -> str:
        to_chains_str = ','.join(map(str, to_chains))
        url = f"https://backend.gas.zip/v2/quotes/{from_chain}/{amount_wei}/{to_chains_str}?to={to_address}&from={from_address}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()['calldata']
        except Exception as e:
            logging.error(f"Error getting calldata: {e}")
            raise

    def execute_refuel(self, w3: Web3, private_key: str, from_chain: int, to_chains: List[int]):
            account = Account.from_key(private_key)
            address = account.address
            
            if self.settings['use_random_amount']:
                amount_wei = self.get_random_amount(
                    self.settings['min_amount'],
                    self.settings['max_amount']
                )
            else:
                amount_wei = Web3.to_wei(self.settings['fixed_amount'], 'ether')

            try:
                calldata = self.get_calldata(
                    from_chain,
                    amount_wei,
                    to_chains,
                    address,
                    address
                )

                tx = {
                    'from': address,
                    'to': self.gas_contract,
                    'value': amount_wei,
                    'nonce': w3.eth.get_transaction_count(address),
                    'data': calldata,
                    'chainId': from_chain
                }

                estimated_gas = w3.eth.estimate_gas(tx)
                tx['gas'] = int(estimated_gas * self.settings['gas_multiplier'])
                
                if 'max_gas_price' in self.settings:
                    tx['gasPrice'] = min(
                        w3.eth.gas_price,
                        Web3.to_wei(self.settings['max_gas_price'], 'gwei')
                    )
                else:
                    tx['gasPrice'] = w3.eth.gas_price

                signed = w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                
                logging.info(f"Transaction sent: {tx_hash.hex()}")
                return tx_hash.hex()

            except Exception as e:
                logging.error(f"Error executing refuel: {e}")
                raise

    def run(self):
        for private_key in self.private_keys:
            for refuel_config in self.settings['refuel_configs']:
                try:
                    w3 = Web3(Web3.HTTPProvider(refuel_config['from_chain_rpc']))
                    
                    tx_hash = self.execute_refuel(
                        w3,
                        private_key,
                        refuel_config['from_chain_id'],
                        refuel_config['to_chain_ids']
                    )
                    
                    if self.settings.get('wait_for_confirmation', False):
                        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                        logging.info(f"Transaction confirmed: {receipt['status']}")
                    
                    delay = random.randint(
                        self.settings['min_delay'],
                        self.settings['max_delay']
                    )
                    logging.info(f"Waiting {delay} seconds before next transaction")
                    time.sleep(delay)
                    
                except Exception as e:
                    logging.error(f"Error processing wallet: {e}")
                    continue

if __name__ == "__main__":
    try:
        refueler = AutoRefuel()
        refueler.run()
    except Exception as e:
        logging.error(f"Program error: {e}")
