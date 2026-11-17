"""Explicit conditional sales workflow; every build owns fresh nodes."""

from google.adk.workflow import START, Edge, Workflow

from .nodes import AssembleNode, ChartNode, IngestNode


def build_workflow() -> Workflow:
    ingest = IngestNode(name="ingest")
    chart = ChartNode(name="chart")
    assemble = AssembleNode(name="assemble")
    return Workflow(
        name="sales_workflow",
        edges=[
            (START, ingest),
            Edge(from_node=ingest, to_node=chart, route="chart"),
            Edge(from_node=ingest, to_node=assemble, route="skip"),
            (chart, assemble),
        ],
    )
