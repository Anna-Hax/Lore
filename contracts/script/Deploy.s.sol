// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {LoreRoles} from "../src/LoreRoles.sol";
import {TopicGraph} from "../src/TopicGraph.sol";
import {Submissions} from "../src/Submissions.sol";
import {Access} from "../src/Access.sol";
import {Royalties} from "../src/Royalties.sol";
import {Reports} from "../src/Reports.sol";
import {PersonRegistry} from "../src/PersonRegistry.sol";
import {AuthorTokens} from "../src/AuthorTokens.sol";
import {LockVault} from "../src/LockVault.sol";
import {MockComfy} from "../src/MockComfy.sol";
import {IComfyRouter, IComfyPoolManager} from "../src/interfaces/IComfy.sol";

/// @notice Deploys every Lore contract, wires them, grants roles and writes
///         shared/lore_shared/deployments/<chainId>.json. Every amount is native 0G.
///
/// Env:
///   DEPLOYER_PRIVATE_KEY   required, except on anvil (31337), which always uses anvil account #0
///   TREASURY               default: deployer
///   VERIFIER, CURATOR      role wallets of the verifier and curator agents (default: deployer)
///   LEAK_DETECTOR          the gateway agent's wallet; it calls recordMatch (default: deployer)
///   REGISTRAR              the gateway agent's wallet; it records agent -> person and author tokens (default: deployer)
///   COMFY_ROUTER, COMFY_POOL_MANAGER, COMFY_LAUNCHER, COMFY_FROM_BLOCK
///                          comfy's contracts and the launcher's first block (0G mainnet: spike/comfy_c1.py has them).
///                          If COMFY_ROUTER is unset, a MockComfy is deployed and plays all three: the Galileo test mirror.
///
/// Then run `python script/export_abi.py` to refresh shared/lore_shared/abi/.
contract Deploy is Script {
    // Anvil's well-known account #0. Only ever used when chainid == 31337.
    uint256 internal constant ANVIL_KEY_0 = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;

    struct Deployed {
        LoreRoles roles;
        TopicGraph graph;
        Royalties royalties;
        Submissions subs;
        Access access;
        Reports reports;
        PersonRegistry registry;
        AuthorTokens authorTokens;
        LockVault vault;
        address router;
        address poolManager;
        address launcher;
        uint256 comfyFromBlock;
    }

    struct Roles {
        address admin;
        address treasury;
        address verifier;
        address curator;
        address detector;
        address registrar;
    }

    function run() external returns (Deployed memory d) {
        uint256 pk = block.chainid == 31337 ? ANVIL_KEY_0 : vm.envUint("DEPLOYER_PRIVATE_KEY");
        Roles memory r;
        r.admin = vm.addr(pk);
        r.treasury = vm.envOr("TREASURY", r.admin);
        r.verifier = vm.envOr("VERIFIER", r.admin);
        r.curator = vm.envOr("CURATOR", r.admin);
        r.detector = vm.envOr("LEAK_DETECTOR", r.admin);
        r.registrar = vm.envOr("REGISTRAR", r.admin);
        d.router = vm.envOr("COMFY_ROUTER", address(0));
        d.poolManager = vm.envOr("COMFY_POOL_MANAGER", address(0));
        d.launcher = vm.envOr("COMFY_LAUNCHER", address(0));
        d.comfyFromBlock = vm.envOr("COMFY_FROM_BLOCK", uint256(0));
        bool mock = d.router == address(0);
        uint256 deployBlock = block.number;

        vm.startBroadcast(pk);
        if (mock) {
            MockComfy m = new MockComfy();
            (d.router, d.poolManager, d.launcher, d.comfyFromBlock) = (address(m), address(m), address(m), block.number);
        }
        d.roles = new LoreRoles(r.admin, r.treasury);
        d.graph = new TopicGraph(d.roles);
        d.royalties = new Royalties(d.roles, d.graph);
        d.subs = new Submissions(d.roles, d.graph);
        d.authorTokens = new AuthorTokens(d.roles, IComfyPoolManager(d.poolManager));
        d.vault = new LockVault(d.roles);
        d.access = new Access(d.roles, d.graph, d.royalties, d.authorTokens, d.vault, IComfyRouter(d.router));
        d.reports = new Reports(d.roles, d.graph);
        d.registry = new PersonRegistry(d.roles);

        d.graph.setSubmissions(address(d.subs));
        d.graph.setRoyalties(address(d.royalties));
        d.graph.setRegistry(address(d.registry));
        d.royalties.setAccess(address(d.access));
        d.subs.setAuthorTokens(address(d.authorTokens));
        d.vault.setAccess(address(d.access));
        d.roles.grantRole(d.roles.VERIFIER_ROLE(), r.verifier);
        d.roles.grantRole(d.roles.CURATOR_ROLE(), r.curator);
        d.roles.grantRole(d.roles.LEAK_DETECTOR_ROLE(), r.detector);
        d.roles.grantRole(d.roles.REGISTRAR_ROLE(), r.registrar);
        vm.stopBroadcast();

        _write(d, r, mock, deployBlock);
    }

    function _write(Deployed memory d, Roles memory roles, bool mockComfy, uint256 deployBlock) internal {
        string memory c = "contracts";
        vm.serializeAddress(c, "LoreRoles", address(d.roles));
        vm.serializeAddress(c, "TopicGraph", address(d.graph));
        vm.serializeAddress(c, "Royalties", address(d.royalties));
        vm.serializeAddress(c, "Submissions", address(d.subs));
        vm.serializeAddress(c, "Access", address(d.access));
        vm.serializeAddress(c, "PersonRegistry", address(d.registry));
        vm.serializeAddress(c, "AuthorTokens", address(d.authorTokens));
        vm.serializeAddress(c, "LockVault", address(d.vault));
        vm.serializeAddress(c, "ComfyRouter", d.router);
        vm.serializeAddress(c, "ComfyPoolManager", d.poolManager);
        vm.serializeAddress(c, "ComfyLauncher", d.launcher);
        string memory contractsJson = vm.serializeAddress(c, "Reports", address(d.reports));

        string memory r = "roles";
        vm.serializeAddress(r, "admin", roles.admin);
        vm.serializeAddress(r, "treasury", roles.treasury);
        vm.serializeAddress(r, "verifier", roles.verifier);
        vm.serializeAddress(r, "curator", roles.curator);
        vm.serializeAddress(r, "leakDetector", roles.detector);
        string memory rolesJson = vm.serializeAddress(r, "registrar", roles.registrar);

        string memory o = "out";
        vm.serializeUint(o, "chainId", block.chainid);
        vm.serializeUint(o, "deployBlock", deployBlock);
        vm.serializeBool(o, "mockComfy", mockComfy);
        vm.serializeUint(o, "comfyFromBlock", d.comfyFromBlock);
        vm.serializeString(o, "roles", rolesJson);
        string memory json = vm.serializeString(o, "contracts", contractsJson);

        string memory path =
            string.concat(vm.projectRoot(), "/../shared/lore_shared/deployments/", vm.toString(block.chainid), ".json");
        vm.writeJson(json, path);
        console2.log("Wrote", path);
    }
}
