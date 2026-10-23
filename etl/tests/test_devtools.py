"""devtools finds the outputs of the stack `./dev azure up` applied."""
import json

from devtools.__main__ import terraform_outputs


def test_outputs_come_from_the_dev_azure_state(tmp_path):
    state = tmp_path / "terraform.tfstate"
    state.write_text(json.dumps({"outputs": {"resource_group": {"value": "rg-itg-etl-dev", "type": "string"}}}))
    assert terraform_outputs(state) == {"resource_group": "rg-itg-etl-dev"}
