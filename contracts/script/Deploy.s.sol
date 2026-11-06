// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {LoreRoles} from "../src/LoreRoles.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {TopicGraph} from "../src/TopicGraph.sol";
import {Submissions} from "../src/Submissions.sol";
import {Access} from "../src/Access.sol";
import {Royalties} from "../src/Royalties.sol";
import {Reports} from "../src/Reports.sol";
import {PersonRegistry} from "../src/PersonRegistry.sol";

/// @notice Deploys every Lore contract, wires them, grants roles and writes
///         shared/lore_shared/deployments/<chainId>.json.
///
/// Env:
///   DEPLOYER_PRIVATE_KEY   required, except on anvil (31337), which always uses anvil account #0
///   TREASURY               default: deployer
///   VERIFIER, CURATOR      role wallets of the verifier and curator agents (default: deployer)
///   LEAK_DETECTOR          the gateway agent's wallet; it calls recordMatch (default: deployer)
///   REGISTRAR              the gateway agent's wallet; it records agent -> World ID person (default: deployer)
///   USDC                   existing USDC address; if unset, a MockUSDC is deployed
///
/// Then run `python script/export_abi.py` to refresh shared/lore_shared/abi/.
contract Deploy is Script {
    // Anvil's well-known account #0. Only ever used when chainid == 31337.
    uint256 internal constant ANVIL_KEY_0 = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;

    struct Deployed {
        LoreRoles roles;
        address usdc;
        TopicGraph graph;
        Royalties royalties;
        Submissions subs;
        Access access;
        Reports reports;
        PersonRegistry registry;
    }

    function run() external returns (Deployed memory d) {
        uint256 pk = block.chainid == 31337
            ? ANVIL_KEY_0
            : vm.envUint("DEPLOYER_PRIVATE_KEY");
        address deployer = vm.addr(pk);
        address treasury = vm.envOr("TREASURY", deployer);
        address verifier = vm.envOr("VERIFIER", deployer);
        address curator = vm.envOr("CURATOR", deployer);
        address detector = vm.envOr("LEAK_DETECTOR", deployer);
        address registrar = vm.envOr("REGISTRAR", deployer);
        address usdcAddr = vm.envOr("USDC", address(0));
        uint256 deployBlock = block.number;

        vm.startBroadcast(pk);
        d.roles = new LoreRoles(deployer, treasury);
        d.usdc = usdcAddr == address(0) ? address(new MockUSDC()) : usdcAddr;
        d.graph = new TopicGraph(d.roles);
        d.royalties = new Royalties(d.roles, IERC20(d.usdc), d.graph);
        d.subs = new Submissions(d.roles, IERC20(d.usdc), d.graph);
        d.access = new Access(d.roles, IERC20(d.usdc), d.graph, d.royalties);
        d.reports = new Reports(d.roles, d.graph);
        d.registry = new PersonRegistry(d.roles);

        d.graph.setSubmissions(address(d.subs));
        d.graph.setRoyalties(address(d.royalties));
        d.graph.setRegistry(address(d.registry));
        d.royalties.setAccess(address(d.access));
        d.roles.grantRole(d.roles.VERIFIER_ROLE(), verifier);
        d.roles.grantRole(d.roles.CURATOR_ROLE(), curator);
        d.roles.grantRole(d.roles.LEAK_DETECTOR_ROLE(), detector);
        d.roles.grantRole(d.roles.REGISTRAR_ROLE(), registrar);
        vm.stopBroadcast();

        _write(d, deployer, treasury, verifier, curator, detector, registrar, usdcAddr == address(0), deployBlock);
    }

    function _write(
        Deployed memory d,
        address deployer,
        address treasury,
        address verifier,
        address curator,
        address detector,
        address registrar,
        bool mockUsdc,
        uint256 deployBlock
    ) internal {
        string memory c = "contracts";
        vm.serializeAddress(c, "LoreRoles", address(d.roles));
        vm.serializeAddress(c, "USDC", d.usdc);
        vm.serializeAddress(c, "TopicGraph", address(d.graph));
        vm.serializeAddress(c, "Royalties", address(d.royalties));
        vm.serializeAddress(c, "Submissions", address(d.subs));
        vm.serializeAddress(c, "Access", address(d.access));
        vm.serializeAddress(c, "PersonRegistry", address(d.registry));
        string memory contractsJson = vm.serializeAddress(c, "Reports", address(d.reports));

        string memory r = "roles";
        vm.serializeAddress(r, "admin", deployer);
        vm.serializeAddress(r, "treasury", treasury);
        vm.serializeAddress(r, "verifier", verifier);
        vm.serializeAddress(r, "curator", curator);
        vm.serializeAddress(r, "leakDetector", detector);
        string memory rolesJson = vm.serializeAddress(r, "registrar", registrar);

        string memory o = "out";
        vm.serializeUint(o, "chainId", block.chainid);
        vm.serializeUint(o, "deployBlock", deployBlock);
        vm.serializeBool(o, "mockUsdc", mockUsdc);
        vm.serializeString(o, "roles", rolesJson);
        string memory json = vm.serializeString(o, "contracts", contractsJson);

        string memory path =
            string.concat(vm.projectRoot(), "/../shared/lore_shared/deployments/", vm.toString(block.chainid), ".json");
        vm.writeJson(json, path);
        console2.log("Wrote", path);
    }
}
