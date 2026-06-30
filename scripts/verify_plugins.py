"""Verify the plugin system is working correctly."""
from carib_clear.plugin import PluginRegistry

r = PluginRegistry()
r.discover()

print('=== Settlement Rails ===')
for rail in r.get_plugins('settlement_rail'):
    print(f'  {rail["id"]}: {rail["metadata"]["currencies"]}')

print()
print('=== Lenders ===')
for lender in r.get_plugins('lender'):
    m = lender['metadata']
    print(f'  {lender["id"]}: jur={m["jurisdictions"]}, max=${m["max_loan_usd"]:,}, collateral={m["requires_collateral"]}')

print()
print('=== Query Tests ===')
print(f'Rails for BBD->JMD: {[r["id"] for r in r.get_rails_for_pair("BBD", "JMD")]}')
print(f'Lenders in HT: {[l["id"] for l in r.get_lenders_for_jurisdiction("HT")]}')
print(f'Lenders in BB: {[l["id"] for l in r.get_lenders_for_jurisdiction("BB")]}')
print(f'Lenders in JM: {[l["id"] for l in r.get_lenders_for_jurisdiction("JM")]}')
print(f'Instantiate stellar_usdc: {r.instantiate("stellar_usdc") is not None}')
