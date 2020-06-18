"""
Command line interface for CasperLabsClient.
"""

import argparse
import textwrap
import base64
import sys
import os
import functools
from pathlib import Path
from casperlabs_client.arg_types import positive_integer

from casperlabs_client import (
    CasperLabsClient,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_INTERNAL_PORT,
    bundled_contract,
)
from casperlabs_client.commands import deploy_cmd
from casperlabs_client.utils import hexify, jsonify
from casperlabs_client.abi import ABI
from casperlabs_client.crypto import (
    read_pem_key,
    generate_validators_keys,
    generate_key_pair,
    public_address,
    private_to_public_key,
    generate_certificates,
)
from . import consensus_pb2 as consensus

DEFAULT_PAYMENT_AMOUNT = 10000000

DOT_FORMATS = "canon,cmap,cmapx,cmapx_np,dot,dot_json,eps,fig,gd,gd2,gif,gv,imap,imap_np,ismap,jpe,jpeg,jpg,json,json0,mp,pdf,pic,plain,plain-ext,png,pov,ps,ps2,svg,svgz,tk,vml,vmlz,vrml,wbmp,x11,xdot,xdot1.2,xdot1.4,xdot_json,xlib"


def guarded_command(function):
    """
    Decorator of functions that implement CLI commands.

    Occasionally the node can throw some exceptions instead of properly sending us a response,
    those will be deserialized on our end and rethrown by the gRPC layer.
    In this case we want to catch the exception and return a non-zero return code to the shell.

    :param function:  function to be decorated
    :return:
    """

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            rc = function(*args, **kwargs)
            # Generally the CLI commands are assumed to succeed if they don't throw,
            # but they can also return a positive error code if they need to.
            if rc is not None:
                return rc
            return 0
        except Exception as e:
            print(str(e), file=sys.stderr)
            return 1

    return wrapper


def _show_blocks(response, element_name="block"):
    count = 0
    for block in response:
        print(f"------------- {element_name} {count} ---------------")
        print(hexify(block))
        print("-----------------------------------------------------\n")
        count += 1
    print("count:", count)


def _show_block(response):
    print(hexify(response))


def _set_session(args, file_name):
    """
    Use bundled contract unless one of the session* args is set.
    """
    if not any((args.session, args.session_hash, args.session_name, args.session_uref)):
        args.session = bundled_contract(file_name)


@guarded_command
def transfer_command(casperlabs_client, args):
    _set_session(args, "transfer_to_account_u512.wasm")

    if not args.session_args:
        target_account_bytes = base64.b64decode(args.target_account)
        if len(target_account_bytes) != 32:
            target_account_bytes = bytes.fromhex(args.target_account)
            if len(target_account_bytes) != 32:
                raise Exception(
                    "--target_account must be 32 bytes base64 or base16 encoded"
                )

        args.session_args = ABI.args_to_json(
            ABI.args(
                [
                    ABI.account("account", target_account_bytes),
                    ABI.u512("amount", args.amount),
                ]
            )
        )

    return deploy_command(casperlabs_client, args)


def _deploy_kwargs(args, private_key_accepted=True):
    from_addr = (
        getattr(args, "from")
        and bytes.fromhex(getattr(args, "from"))
        or getattr(args, "public_key")
        and read_pem_key(args.public_key)
        or private_to_public_key(args.private_key)
    )
    if from_addr and len(from_addr) != 32:
        raise Exception(
            "--from must be 32 bytes encoded as 64 characters long hexadecimal"
        )

    if not (args.payment_amount or args.payment_args):
        args.payment_amount = DEFAULT_PAYMENT_AMOUNT

    if args.payment_amount:
        args.payment_args = ABI.args_to_json(
            ABI.args([ABI.big_int("amount", int(args.payment_amount))])
        )

    d = dict(
        from_addr=from_addr,
        gas_price=args.gas_price,
        payment=args.payment,
        session=args.session,
        public_key=args.public_key or None,
        session_args=args.session_args
        and ABI.args_from_json(args.session_args)
        or None,
        payment_args=args.payment_args
        and ABI.args_from_json(args.payment_args)
        or None,
        payment_hash=args.payment_hash and bytes.fromhex(args.payment_hash),
        payment_name=args.payment_name,
        payment_package_hash=args.payment_package_hash
        and bytes.fromhex(args.payment_package_hash),
        payment_package_name=args.payment_package_name,
        payment_entry_point=args.payment_entry_point,
        payment_version=args.payment_version,
        session_hash=args.session_hash and bytes.fromhex(args.session_hash),
        session_name=args.session_name,
        session_package_hash=args.session_package_hash
        and bytes.fromhex(args.session_package_hash),
        session_package_name=args.session_package_name,
        session_entry_point=args.session_entry_point,
        session_sem_ver=args.session_sem_ver,
        ttl_millis=args.ttl_millis,
        dependencies=args.dependencies,
        chain_name=args.chain_name,
    )
    if private_key_accepted:
        d["private_key"] = args.private_key or None
    return d


@guarded_command
def make_deploy_command(casperlabs_client, args):
    kwargs = _deploy_kwargs(args, private_key_accepted=False)
    deploy = casperlabs_client.make_deploy(**kwargs)
    data = deploy.SerializeToString()
    if not args.deploy_path:
        sys.stdout.buffer.write(data)
    else:
        with open(args.deploy_path, "wb") as f:
            f.write(data)


@guarded_command
def sign_deploy_command(casperlabs_client, args):
    deploy = consensus.Deploy()
    if args.deploy_path:
        with open(args.deploy_path, "rb") as input_file:
            deploy.ParseFromString(input_file.read())
    else:
        deploy.ParseFromString(sys.stdin.read())

    deploy = casperlabs_client.sign_deploy(
        deploy, read_pem_key(args.public_key), args.private_key
    )

    if not args.signed_deploy_path:
        sys.stdout.write(deploy.SerializeToString())
    else:
        with open(args.signed_deploy_path, "wb") as output_file:
            output_file.write(deploy.SerializeToString())


@guarded_command
def send_deploy_command(casperlabs_client, args):
    deploy = consensus.Deploy()
    with open(args.deploy_path, "rb") as f:
        deploy.ParseFromString(f.read())
        casperlabs_client.send_deploy(deploy)
    print(f"Success! Deploy {deploy.deploy_hash.hex()} deployed")


@guarded_command
def deploy_command(casperlabs_client, args):
    kwargs = _deploy_kwargs(args)
    deploy_hash = casperlabs_client.deploy(**kwargs)
    print(f"Success! Deploy {deploy_hash} deployed")
    if args.wait_for_processed:
        deploy_info = casperlabs_client.showDeploy(
            deploy_hash,
            full_view=False,
            wait_for_processed=args.wait_for_processed,
            timeout_seconds=args.timeout_seconds,
        )
        print(hexify(deploy_info))


@guarded_command
def propose_command(casperlabs_client, args):
    print("Warning: command propose is deprecated.", file=sys.stderr)
    response = casperlabs_client.propose()
    print(f"Success! Block hash: {response.block_hash.hex()}")


@guarded_command
def show_block_command(casperlabs_client, args):
    response = casperlabs_client.showBlock(args.hash, full_view=True)
    return _show_block(response)


@guarded_command
def show_blocks_command(casperlabs_client, args):
    response = casperlabs_client.showBlocks(args.depth, full_view=False)
    _show_blocks(response)


@guarded_command
def vdag_command(casperlabs_client, args):
    for o in casperlabs_client.visualizeDag(
        args.depth, args.out, args.show_justification_lines, args.stream
    ):
        if not args.out:
            print(o)
            break


@guarded_command
def query_state_command(casperlabs_client, args):

    response = casperlabs_client.queryState(
        args.block_hash, args.key, args.path or "", getattr(args, "type")
    )
    print(hexify(response))


@guarded_command
def balance_command(casperlabs_client, args):
    response = casperlabs_client.balance(args.address, args.block_hash)
    print(response)


@guarded_command
def show_deploy_command(casperlabs_client, args):
    response = casperlabs_client.showDeploy(
        args.hash,
        full_view=False,
        wait_for_processed=args.wait_for_processed,
        timeout_seconds=args.timeout_seconds,
    )
    print(hexify(response))


@guarded_command
def show_deploys_command(casperlabs_client, args):
    response = casperlabs_client.showDeploys(args.hash, full_view=False)
    _show_blocks(response, element_name="deploy")


def write_file(file_name, text):
    with open(file_name, "w") as f:
        f.write(text)


def write_binary_file(file_name, data):
    with open(file_name, "wb") as f:
        f.write(data)


def encode_base64(a: bytes):
    return str(base64.b64encode(a), "utf-8")


@guarded_command
def keygen_command(casperlabs_client, args):
    directory = Path(args.directory).resolve()
    validator_private_path = directory / "validator-private.pem"
    validator_pub_path = directory / "validator-public.pem"
    validator_id_path = directory / "validator-id"
    validator_id_hex_path = directory / "validator-id-hex"
    node_priv_path = directory / "node.key.pem"
    node_cert_path = directory / "node.certificate.pem"
    node_id_path = directory / "node-id"

    (
        validator_private_pem,
        validator_public_pem,
        validator_public_bytes,
    ) = generate_validators_keys()
    write_binary_file(validator_private_path, validator_private_pem)
    write_binary_file(validator_pub_path, validator_public_pem)
    write_file(validator_id_path, encode_base64(validator_public_bytes))
    write_file(validator_id_hex_path, validator_public_bytes.hex())

    private_key, public_key = generate_key_pair()

    node_cert, key_pem = generate_certificates(private_key, public_key)

    write_binary_file(node_priv_path, key_pem)
    write_binary_file(node_cert_path, node_cert)

    write_file(node_id_path, public_address(public_key))
    print(f"Keys successfully created in directory: {str(directory.absolute())}")


@guarded_command
def show_peers_command(casperlabs_client, args):
    peers = casperlabs_client.show_peers()
    i = 0
    for i, node in enumerate(peers, 1):
        print(f"------------- node {i} ---------------")
        print(hexify(node))
    print("-----------------------------------------------------")
    print(f"count: {i}")


@guarded_command
def stream_events_command(casperlabs_client, args):
    subscribed_events = dict(
        all=args.all,
        block_added=args.block_added,
        block_finalized=args.block_finalized,
        deploy_added=args.deploy_added,
        deploy_discarded=args.deploy_discarded,
        deploy_requeued=args.deploy_requeued,
        deploy_processed=args.deploy_processed,
        deploy_finalized=args.deploy_finalized,
        deploy_orphaned=args.deploy_orphaned,
    )
    if not any(subscribed_events.values()):
        raise argparse.ArgumentTypeError("No events chosen")

    stream = casperlabs_client.stream_events(
        account_public_keys=args.account_public_key,
        deploy_hashes=args.deploy_hash,
        min_event_id=args.min_event_id,
        max_event_id=args.max_event_id,
        **subscribed_events,
    )
    for event in stream:
        if args.format == "binary":
            print(base64.b64encode(event.SerializeToString()).decode())
        elif args.format == "json":
            print(jsonify(event))
        else:
            print(hexify(event))


def directory_for_write(path):
    if not os.path.exists(path):
        raise argparse.ArgumentTypeError(f"Directory '{path}' does not exist")
    if not os.path.isdir(path):
        raise argparse.ArgumentTypeError(f"'{path}' is not a directory")
    if not os.access(path, os.W_OK):
        raise argparse.ArgumentTypeError(f"'{path}' does not have writing permissions")
    return Path(path)


def dot_output(file_name):
    """
    Check file name has an extension of one of file formats supported by Graphviz.
    """
    parts = file_name.split(".")
    if len(parts) == 1:
        raise argparse.ArgumentTypeError(
            f"'{file_name}' has no extension indicating file format"
        )
    else:
        file_format = parts[-1]
        if file_format not in DOT_FORMATS.split(","):
            raise argparse.ArgumentTypeError(
                f"File extension {file_format} not recognized, must be one of {DOT_FORMATS}"
            )
    return file_name


def read_version() -> str:
    version_path = Path(os.path.dirname(os.path.realpath(__file__))) / "VERSION"
    with open(version_path, "r") as f:
        return f.read().strip()


def cli(*arguments) -> int:
    """
    Parse list of command line arguments and call appropriate command.
    """

    class Parser:
        def __init__(self):
            # The --help option added by default has a short version -h, which conflicts
            # with short version of --host, so we need to disable it.
            self.parser = argparse.ArgumentParser(
                prog="casperlabs_client", add_help=False
            )
            self.parser.add_argument(
                "--help",
                action="help",
                default=argparse.SUPPRESS,
                help="show this help message and exit",
            )
            self.parser.add_argument(
                "-h",
                "--host",
                required=False,
                default=DEFAULT_HOST,
                type=str,
                help="Hostname or IP of node on which gRPC service is running.",
            )
            self.parser.add_argument(
                "-p",
                "--port",
                required=False,
                default=DEFAULT_PORT,
                type=int,
                help="Port used for external gRPC API.",
            )
            self.parser.add_argument(
                "--port-internal",
                required=False,
                default=DEFAULT_INTERNAL_PORT,
                type=int,
                help="Port used for internal gRPC API.",
            )
            self.parser.add_argument(
                "--node-id",
                required=False,
                type=str,
                help="node_id parameter for TLS connection",
            )
            self.parser.add_argument(
                "--certificate-file",
                required=False,
                type=str,
                help="Certificate file for TLS connection",
            )
            self.parser.add_argument(
                "--version", action="version", version=read_version()
            )
            self.sp = self.parser.add_subparsers(help="Choose a request")

            def no_command(casperlabs_client, args):
                print(
                    "You must provide a command. --help for documentation of commands."
                )
                self.parser.print_usage()
                return 1

            self.parser.set_defaults(function=no_command)

        def addCommand(self, command: str, function, help, arguments):
            command_parser = self.sp.add_parser(command, help=help)
            command_parser.set_defaults(function=function)
            for (args, options) in arguments:
                command_parser.add_argument(*args, **options)

        def run(self, argv):
            args = self.parser.parse_args(argv)
            return args.function(
                CasperLabsClient(
                    args.host,
                    args.port,
                    args.port_internal,
                    args.node_id,
                    args.certificate_file,
                ),
                args,
            )

    parser = Parser()

    # fmt: off
    parser.addCommand(deploy_cmd.COMMAND_NAME, deploy_command, deploy_cmd.HELP_TEXT, deploy_cmd.DEPLOY_OPTIONS_PRIVATE)

    parser.addCommand('make-deploy', make_deploy_command, "Constructs a deploy that can be signed and sent to a node.",
                      [[('-o', '--deploy-path'), dict(required=False, help="Path to the file where deploy will be saved. Optional, if not provided the deploy will be printed to STDOUT.")]] + deploy_cmd.DEPLOY_OPTIONS)

    parser.addCommand('sign-deploy', sign_deploy_command, "Cryptographically signs a deploy. The signature is appended to existing approvals.",
                      [[('-o', '--signed-deploy-path'), dict(required=False, default=None, help="Path to the file where signed deploy will be saved. Optional, if not provided the deploy will be printed to STDOUT.")],
                       [('-i', '--deploy-path'), dict(required=False, default=None, help="Path to the deploy file.")],
                       [('--private-key',), dict(required=True, help="Path to the file with account private key (Ed25519)")],
                       [('--public-key',), dict(required=True, help="Path to the file with account public key (Ed25519)")]])

    parser.addCommand('send-deploy', send_deploy_command, "Deploy a smart contract source file to Casper on an existing running node. The deploy will be packaged and sent as a block to the network depending on the configuration of the Casper instance.",
                      [[('-i', '--deploy-path'), dict(required=False, default=None, help="Path to the file with signed deploy.")]])

    parser.addCommand('transfer', transfer_command, 'Transfers funds between accounts',
                      [[('-a', '--amount'), dict(required=True, default=None, type=int, help='Amount of motes to transfer. Note: a mote is the smallest, indivisible unit of a token.')],
                       [('-t', '--target-account'), dict(required=True, type=str, help="base64 or base16 representation of target account's public key")],
                       ] + deploy_cmd.DEPLOY_OPTIONS_PRIVATE)

    parser.addCommand('propose', propose_command, '[DEPRECATED] Force a node to propose a block based on its accumulated deploys.', [])

    parser.addCommand('show-block', show_block_command, 'View properties of a block known by Casper on an existing running node. Output includes: parent hashes, storage contents of the tuplespace.',
                      [[('hash',), dict(type=str, help='the hash value of the block')]])

    parser.addCommand('show-blocks', show_blocks_command, 'View list of blocks in the current Casper view on an existing running node.',
                      [[('-d', '--depth'), dict(required=True, type=int, help='depth in terms of block height')]])

    parser.addCommand('show-deploy', show_deploy_command, 'View properties of a deploy known by Casper on an existing running node.',
                      [[('hash',), dict(type=str, help='Value of the deploy hash, base16 encoded.')],
                       [('-w', '--wait-for-processed'), dict(action='store_true', help='Wait for deploy status PROCESSED or DISCARDED')],
                       [('--timeout-seconds',), dict(type=int, default=deploy_cmd.STATUS_TIMEOUT, help='Timeout in seconds')]])

    parser.addCommand('show-deploys', show_deploys_command, 'View deploys included in a block.',
                      [[('hash',), dict(type=str, help='Value of the block hash, base16 encoded.')]])

    parser.addCommand('vdag', vdag_command, 'DAG in DOT format. You need to install Graphviz from https://www.graphviz.org/ to use it.',
                      [[('-d', '--depth'), dict(required=True, type=positive_integer, help='depth in terms of block height')],
                       [('-o', '--out'), dict(required=False, type=dot_output, help=f'output image filename, outputs to stdout if not specified, must end with one of {DOT_FORMATS}')],
                       [('-s', '--show-justification-lines'), dict(action='store_true', help='if justification lines should be shown')],
                       [('--stream',), dict(required=False, choices=('single-output', 'multiple-outputs'), help="subscribe to changes, '--out' has to be specified, valid values are 'single-output', 'multiple-outputs'")]])

    parser.addCommand('query-state', query_state_command, 'Query a value in the global state.',
                      [[('-b', '--block-hash'), dict(required=True, type=str, help='Hash of the block to query the state of')],
                       [('-k', '--key'), dict(required=True, type=str, help='Base16 encoding of the base key')],
                       [('-p', '--path'), dict(required=False, type=str, help="Path to the value to query. Must be of the form 'key1/key2/.../keyn'")],
                       [('-t', '--type'), dict(required=True, choices=('hash', 'uref', 'address', 'local'), help="Type of base key. Must be one of 'hash', 'uref', 'address' or 'local'. For 'local' key type, 'key' value format is {seed}:{rest}, where both parts are hex encoded.")]])

    parser.addCommand('balance', balance_command, 'Returns the balance of the account at the specified block.',
                      [[('-a', '--address'), dict(required=True, type=str, help="Account's public key in hex.")],
                       [('-b', '--block-hash'), dict(required=True, type=str, help='Hash of the block to query the state of')]])

    parser.addCommand('keygen', keygen_command, textwrap.dedent("""\
         Generate keys.

         Usage: casperlabs-client keygen <existingOutputDirectory>
         Command will override existing files!
         Generated files:
           node-id               # node ID as in casperlabs://c0a6c82062461c9b7f9f5c3120f44589393edf31@<NODE ADDRESS>?protocol=40400&discovery=40404
                                 # derived from node.key.pem
           node.certificate.pem  # TLS certificate used for node-to-node interaction encryption
                                 # derived from node.key.pem
           node.key.pem          # secp256r1 private key
           validator-id          # validator ID in Base64 format; can be used in accounts.csv
                                 # derived from validator.public.pem
           validator-id-hex      # validator ID in hex, derived from validator.public.pem
           validator-private.pem # ed25519 private key
           validator-public.pem  # ed25519 public key"""),
                      [[('directory',), dict(type=directory_for_write, help="Output directory for keys. Should already exists.")]])

    parser.addCommand('show-peers', show_peers_command, "Show peers connected to the node.", [])

    parser.addCommand('stream-events', stream_events_command, "Stream block and deploy state transition events.", [
        [('--all',), dict(action='store_true', help='Subscribe to all events')],
        [('--block-added',), dict(action='store_true', help='Block added')],
        [('--block-finalized',), dict(action='store_true', help='Block finalized')],
        [('--deploy-added',), dict(action='store_true', help='Deploy added')],
        [('--deploy-discarded',), dict(action='store_true', help='Deploy discarded')],
        [('--deploy-requeued',), dict(action='store_true', help='Deploy requeued')],
        [('--deploy-processed',), dict(action='store_true', help='Deploy processed')],
        [('--deploy-finalized',), dict(action='store_true', help='Deploy finalized')],
        [('--deploy-orphaned',), dict(action='store_true', help='Deploy orphaned')],
        [('-k', '--account-public-key'), dict(action='append', help='Filter by (possibly multiple) account public key(s)')],
        [('-d', '--deploy-hash'), dict(action='append', help='Filter by (possibly multiple) deploy hash(es)')],
        [('-f', '--format'), dict(required=False, default='text', choices=('json', 'binary', 'text'), help='Choose output format. Defaults to text representation.')],
        [('--min-event-id',), dict(required=False, default=0, type=int, help="Supports replaying events from a given ID. If the value is 0, it it will subscribe to future events; if it's non-zero, it will replay all past events from that ID, without subscribing to new. To catch up with events from the beginning, start from 1.")],
        [('--max-event-id',), dict(required=False, default=0, type=int, help="Supports replaying events to a given ID.")],
    ])
    # fmt:on
    return parser.run([str(a) for a in arguments])


def main():
    return cli(*sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
