from importlib.resources import files
import json

import pytest

web3 = pytest.importorskip("web3")

from lore_shared.chain import ChainReader  # noqa: E402

DEPLOYMENTS = sorted(int(p.name.removesuffix(".json")) for p in files("lore_shared").joinpath("deployments").iterdir()
                     if p.name.endswith(".json"))


@pytest.mark.parametrize("chain_id", DEPLOYMENTS)
def test_every_deployed_contract_has_a_loadable_abi(chain_id):
    # Offline: binding contracts needs no RPC. Catches a deployment that names a contract the reader can't load.
    reader = ChainReader(chain_id, web3=web3.Web3())
    deployed = json.loads(files("lore_shared").joinpath(f"deployments/{chain_id}.json").read_text())["contracts"]
    assert set(reader.contracts) == set(deployed)
    assert "PersonRegistry" in reader.contracts
