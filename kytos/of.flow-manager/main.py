"""This App is the responsible to install a drop ipv6 flow on switch setup."""

import logging

from flask import request

from kyco.core.events import KycoEvent
from kyco.core.flow import Flow
from kyco.core.napps import KycoCoreNApp
from kyco.utils import listen_to
from pyof.v0x01.common.flow_match import Match
from pyof.v0x01.controller2switch.common import StatsTypes
from pyof.v0x01.controller2switch.flow_mod import FlowModCommand
from pyof.v0x01.controller2switch.stats_request import StatsRequest

STATS_INTERVAL = 30
log = logging.getLogger('flow_manager')


class Main(KycoCoreNApp):
    """Main class of KycoCoreNApp, responsible for the main OpenFlow basic
    operations.

    """

    def setup(self):
        """'Replaces' the 'init' method for the KycoApp subclass.

        The setup method is automatically called by the run method.
        Users shouldn't call this method directly."""
        self.execute_as_loop(STATS_INTERVAL)
        self.flow_manager = FlowManager(self.controller)
        self.controller.register_rest_endpoint('/<dpid>/flows',
                                               self.retrieve_flows,
                                               methods=['GET'])

        self.controller.register_rest_endpoint('/flows',
                                               self.retrieve_flows,
                                               methods=['GET'])

        self.controller.register_rest_endpoint('/<dpid>/flows',
                                               self.insert_flow,
                                               methods=['POST'])

    def execute(self):
        """Method to be runned once on app 'start' or in a loop.

        The execute method is called by the run method of KycoNApp class.
        Users shouldn't call this method directly."""
        for dpid in self.controller.switches:
            self.flow_manager.dump_flows(dpid)

    def shutdown(self):
        self.server.stop()

    def retrieve_flows(self, dpid=None):
        """
        Retrieves all flows from a sitch identified by dpid. If no dpid has
        been specified, returns the flows from all switches
        """
        flows = []
        if dpid is not None:
            flows.append(self.flow_manager.flows[dpid])
        else:
            for switch_dpid in self.flow_manager.flows:
                flows.append(self.flow_manager.flows[switch_dpid])
        return flows

    def insert_flow(self, dpid=None):
        """Insert a new flow to the switch identified by dpid. If no dpid has
        been specified, install flow in all switches """
        json_content = request.get_json()
        received_flow = Flow.from_json(json_content)
        if dpid is not None:
            self.flow_manager.install_new_flow(received_flow, dpid)
        else:
            for switch_dpid in self.controller.switches:
                self.flow_manager.install_new_flow(received_flow, switch_dpid)

    def clear_flows(self, dpid=None):
        """Clear flows from a switch identified by dpid. If no dpid has been
        specified, clear all flows from all switches"""

        if dpid is not None:
            self.flow_manager.clear_flows(dpid)
        else:
            for switch_dpid in self.controller.switches:
                self.flow_manager.clear_flows(switch_dpid)

    def delete_flow(self, flow_id, dpid=None):
        """
        Deletes a flow identified by flow_id from a swith identified by dpid.
        If no dpid has been specified, removes all flows with the given flow_id
        from all switches
        """
        if dpid is not None:
            self.flow_manager.delete_flow(flow_id, dpid)
        else:
            for switch_dpid in self.controller.switches:
                self.flow_manager.delete_flow(flow_id, switch_dpid)


class FlowManager(object):
    """This class is responsible for manipulating flows at the switches"""
    def __init__(self, controller):
        self.controller = controller
        self.flows = {}

    def install_new_flow(self, flow, dpid):
        """
        This method is responsible for creating a new flow_mod message from
        the Flow object received
        """
        switch = self.controller.get_switch_by_dpid(dpid)
        flow_mod = flow.as_flow_mod(FlowModCommand.OFPFC_ADD)

        event_out = KycoEvent(name=('kytos/of.flow-manager.messages.out.'
                                    'ofpt_flow_mod'),
                              content={'destination': switch.connection,
                                       'message': flow_mod})
        self.controller.buffers.msg_out.put(event_out)

    def dump_flows(self, dpid):
        """Rettrieves the list of flows installed in the Switch identified by
        dpid"""
        switch = self.controller.get_switch_by_dpid(dpid)
        stats_request = StatsRequest()
        stats_request.body_type = StatsTypes.OFPST_FLOW
        stats_request.match = Match()
        event_out = KycoEvent(name=('kytos/of.flow-manager.messages.out.'
                                    'ofpt_stats_request'),
                              content={'destination': switch.connection,
                                       'message': stats_request})
        self.controller.buffers.msg_out.put(event_out)

    def clear_flows(self, dpid):
        """Clear all flows from switch identified by dpid"""
        switch = self.controller.get_switch_by_dpid(dpid)
        for flow in self.flows:
            flow_mod = flow.as_flow_mod(FlowModCommand.OFPFC_DELETE)
            event_out = KycoEvent(name=('kytos/of.flow-manager.messages.out.'
                                        'ofpt_flow_mod'),
                                  content={'destination': switch.connection,
                                           'message': flow_mod})
            self.controller.buffers.msg_out.put(event_out)

    def delete_flow(self, flow_id, dpid):
        """Removes the flow identified by id from the switch identified by
        dpid"""
        switch = self.controller.get_switch_by_dpid(dpid)
        for flow in self.flows:
            if flow.id == flow_id:
                flow_mod = flow.as_flow_mod(FlowModCommand.OFPFC_DELETE)
                content = {'destination': switch.connection,
                           'message': flow_mod}
                event_out = KycoEvent(name=('kytos/of.flow-manager.'
                                            'messages.out.ofpt_flow_mod'),
                                      content=content)
                self.controller.buffers.msg_out.put(event_out)

    @listen_to('kytos/of.core.messages.in.ofpt_stats_reply')
    def handle_flow_stats_reply(self, event):
        """Handle Flow Stats messages"""
        msg = event.content['message']
        if msg.body_type.value is StatsTypes.OFPST_FLOW:
            flow_stats = msg.body
            flows = self._get_flows(flow_stats)
            switch_dpid = event.content['switch']
            if self.flows[switch_dpid] is None:
                self.flows[switch_dpid] = []
            self.flows[switch_dpid].append(flows)

    def _get_flows(self, flow_stats):
        """
        Creates a list of flows from the body of a flow_stats_reply
        message
        """
        flows = []
        for flow_stat in flow_stats:
            flows.append(Flow.from_flow_stats(flow_stat))

        return flows
