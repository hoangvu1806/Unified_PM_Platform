import json
from pathlib import Path

from app.attachments.parser import (
    parse_bpmn_document,
    parse_json_document,
    parse_text_document,
)


def test_ba_package_is_compacted_to_traceable_markdown() -> None:
    source = Path(__file__).resolve().parents[2] / "ba-package_usecase_01.json"
    raw = source.read_bytes()

    parsed = parse_json_document(raw)

    assert len(parsed.markdown) < len(raw.decode("utf-8"))
    assert parsed.truncated is False
    assert "# BA handoff context" in parsed.markdown
    assert "Fourth of July flag landing page" in parsed.markdown
    assert "## UI screens to design" in parsed.markdown
    assert "US-01" in parsed.markdown
    assert "AC-01" in parsed.markdown
    assert "BR-04" in parsed.markdown
    assert "E-03" in parsed.markdown
    assert "duplicate acceptance-criterion IDs: `AC-06`" in parsed.markdown
    assert "bpmn_xml_content" not in parsed.markdown
    assert "agent_response" not in parsed.markdown


def test_generic_json_omits_large_machine_fields() -> None:
    parsed = parse_json_document(
        json.dumps(
            {
                "title": "Checkout",
                "requirements": [{"state": "payment failed"}],
                "bpmn_xml_content": "<xml>large</xml>",
            }
        ).encode()
    )

    assert "Checkout" in parsed.markdown
    assert "payment failed" in parsed.markdown
    assert "large" not in parsed.markdown


def test_plain_text_is_wrapped_as_markdown_context() -> None:
    parsed = parse_text_document(b"Login must support SSO", ".txt")

    assert parsed.markdown == "# Attached text context\n\nLogin must support SSO"


def test_bpmn_document_is_parsed_to_structured_process_markdown() -> None:
    bpmn_xml = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_1">
  <bpmn:process id="Process_Checkout" name="E-Commerce Checkout" isExecutable="true">
    <bpmn:documentation>Customer completes checkout and pays.</bpmn:documentation>
    <bpmn:laneSet id="LaneSet_1">
      <bpmn:lane id="Lane_Buyer" name="Shopper">
        <bpmn:flowNodeRef>Start_1</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Task_Address</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Gateway_Method</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Task_Pay</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>End_Success</bpmn:flowNodeRef>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:startEvent id="Start_1" name="Begin Checkout">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="Task_Address" name="Enter Shipping Address">
      <bpmn:documentation>Provide street, city, postal code.</bpmn:documentation>
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:exclusiveGateway id="Gateway_Method" name="Domestic or International?">
      <bpmn:incoming>Flow_2</bpmn:incoming>
      <bpmn:outgoing>Flow_Domestic</bpmn:outgoing>
      <bpmn:outgoing>Flow_Intl</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:userTask id="Task_Pay" name="Select Payment">
      <bpmn:incoming>Flow_Domestic</bpmn:incoming>
      <bpmn:outgoing>Flow_3</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:endEvent id="End_Success" name="Order Placed">
      <bpmn:incoming>Flow_3</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_Address" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_Address" targetRef="Gateway_Method" />
    <bpmn:sequenceFlow id="Flow_Domestic" name="Domestic" sourceRef="Gateway_Method" targetRef="Task_Pay" />
    <bpmn:sequenceFlow id="Flow_3" sourceRef="Task_Pay" targetRef="End_Success" />
  </bpmn:process>
</bpmn:definitions>"""

    parsed = parse_bpmn_document(bpmn_xml.encode("utf-8"))

    assert "# BPMN Business Process Context" in parsed.markdown
    assert "E-Commerce Checkout" in parsed.markdown
    assert "Shopper" in parsed.markdown
    assert "Enter Shipping Address" in parsed.markdown
    assert "Provide street, city, postal code" in parsed.markdown
    assert "Domestic or International?" in parsed.markdown
    assert "Domestic" in parsed.markdown
    assert "Order Placed" in parsed.markdown
    assert parsed.truncated is False


def test_bpmn_document_with_multiple_participants_and_lanes() -> None:
    bpmn_xml = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Def_2">
  <collaboration id="Collab_1">
    <participant id="P_Customer" name="Customer User" processRef="Proc_Cust" />
    <participant id="P_Admin" name="Support Admin" processRef="Proc_Admin" />
    <messageFlow id="MF_1" name="Ticket Raised" sourceRef="Task_Submit" targetRef="Task_Review" />
  </collaboration>
  <process id="Proc_Cust" name="Customer Support Flow">
    <startEvent id="Start_Ticket" name="Issue Encountered" />
    <userTask id="Task_Submit" name="Submit Help Ticket" />
  </process>
  <process id="Proc_Admin" name="Admin Review Flow">
    <userTask id="Task_Review" name="Review Help Ticket" />
    <endEvent id="End_Closed" name="Ticket Resolved" />
  </process>
</definitions>"""

    parsed = parse_bpmn_document(bpmn_xml.encode("utf-8"))

    assert "Customer User" in parsed.markdown
    assert "Support Admin" in parsed.markdown
    assert "Submit Help Ticket" in parsed.markdown
    assert "Review Help Ticket" in parsed.markdown
    assert "Inter-Process Message Flows" in parsed.markdown
    assert "Ticket Raised" in parsed.markdown


def test_bpmn_handles_malformed_xml_gracefully() -> None:
    try:
        parse_bpmn_document(b"<invalid<xml")
        raise AssertionError("Should raise ValueError on invalid XML")
    except ValueError as err:
        assert "Failed to parse BPMN XML" in str(err)
