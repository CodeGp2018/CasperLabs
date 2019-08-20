from test.cl_node.casperlabs_accounts import Account
from test.cl_node.common import HELLO_NAME_CONTRACT


def test_non_account_precondition_failure(one_node_network):
    node = one_node_network.docker_nodes[0]

    # Getting a non-existent account
    non_existent_account = Account(300)

    result = node.p_client.deploy(
        from_address=non_existent_account.public_key_hex,
        public_key=non_existent_account.public_key_path,
        private_key=non_existent_account.private_key_path,
        session_contract=HELLO_NAME_CONTRACT,
        payment_contract=HELLO_NAME_CONTRACT,
    )
    print(result)
