# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import xml.etree.ElementTree as ET
from fwunit.ip import IP, IPSet
from logging import getLogger

log = getLogger(__name__)


class Policy(object):

    def __init__(self):
        #: policy name
        self.name = None

        #: source zone name for this policy
        self.from_zone = None

        #: destination zone name for this policy
        self.to_zone = None

        #: boolean, true if the policy is enabled
        self.enabled = None

        #: policy sequence number
        self.sequence = None

        #: source addresses (by name) for the policy
        self.source_addresses = []

        #: destination addresses (by name) for the policy
        self.destination_addresses = []

        #: applications (name) for the policy
        self.applications = []

        #: 'permit' or 'deny'
        self.action = None

    def __str__(self):
        return ("%(action)s %(from_zone)s:%(source_addresses)r -> "
                "%(to_zone)s:%(destination_addresses)r : %(applications)s") % self.__dict__

    @classmethod
    def _from_xml(cls, from_zone, to_zone, policy_information_elt):
        pol = cls()
        pie = policy_information_elt
        pol.name = pie.find('./policy-name').text
        pol.from_zone = from_zone
        pol.to_zone = to_zone
        pol.enabled = pie.find('./policy-state').text == 'enabled'
        pol.sequence = int(pie.find('./policy-sequence-number').text)
        pol.source_addresses = [
            pol._parse_address(e) for e in pie.findall('./source-addresses/*')]
        pol.destination_addresses = [
            pol._parse_address(e) for e in pie.findall('./destination-addresses/*')]
        pol.applications = [
            pol._parse_application(e) for e in pie.findall('./applications/application')]
        pol.action = pie.find('./policy-action/action-type').text
        return pol

    def _parse_address(self, elt):
        addrname = elt.find('./address-name')
        return addrname.text

    def _parse_application(self, elt):
        appname = elt.find('./application-name')
        return appname.text


class Route(object):

    """A route from the firewall's routing table"""

    def __init__(self):
        #: IPSet based on the route destination
        self.destination = None

        #: interface to which traffic is forwarded (via or local)
        self.interface = None

        #: true if this destination is local (no next-hop IP)
        self.is_local = None

    def __str__(self):
        return "%s via %s" % (self.destination, self.interface)

    @classmethod
    def _from_xml(cls, rt_elt):
        route = cls()
        route.destination = IP(rt_elt.find(
            '{http://xml.juniper.net/junos/12.1X44/junos-routing}rt-destination').text)
        for entry in rt_elt.findall('{http://xml.juniper.net/junos/12.1X44/junos-routing}rt-entry'):
            if entry.findall('.//{http://xml.juniper.net/junos/12.1X44/junos-routing}current-active'):
                vias = entry.findall(
                    './/{http://xml.juniper.net/junos/12.1X44/junos-routing}via')
                if vias:
                    route.interface = vias[0].text
                route.is_local = not bool(
                    entry.findall(
                        './/{http://xml.juniper.net/junos/12.1X44/junos-routing}to'))
        # only return a Route if we found something useful (omitting nh-local-interface)
        if route.interface:
            return route


class Zone(object):

    """Parse out zone names and the corresponding interfaces"""

    def __init__(self):
        #: list of interface names
        self.interfaces = []

        #: name -> ipset, based on the zone's address book
        self.addresses = {'any': IPSet([IP('0.0.0.0/0')])}

    def __str__(self):
        return "%s on %s" % (self.name, self.interfaces)

    @classmethod
    def _from_xml(cls, security_zone_elt):
        zone = cls()
        sze = security_zone_elt
        zone.name = sze.find('name').text

        # interfaces
        for itfc in sze.findall('.//interfaces/name'):
            zone.interfaces.append(itfc.text)

        # address book
        for addr in sze.find('address-book'):
            name = addr.findtext('name')
            if addr.tag == 'address':
                ip = IPSet([IP(addr.findtext('ip-prefix'))])
            else:  # note: assumes address-sets follow addresses
                ip = IPSet()
                for setaddr in addr.findall('address'):
                    setname = setaddr.findtext('name')
                    ip += zone.addresses[setname]
            zone.addresses[name] = ip
        return zone


class Firewall(object):

    def __init__(self, security_policies_xml,
                 route_xml, configuration_security_zones_xml):

        #: list of Policy instances
        self.policies = self._parse_policies(security_policies_xml)

        #: list of Route instances from 'inet.0'
        self.routes = self._parse_routes(route_xml)

        #: list of security zones
        self.zones = self._parse_zones(configuration_security_zones_xml)

    def _parse_policies(self, security_policies_xml):
        log.info("parsing policies")
        sspe = ET.parse(security_policies_xml).getroot()
        policies = []
        for elt in sspe.findall('.//security-context'):
            from_zone = elt.find('./context-information/source-zone-name').text
            to_zone = elt.find(
                './context-information/destination-zone-name').text
            for pol_elt in elt.findall('./policies/policy-information'):
                policy = Policy._from_xml(from_zone, to_zone, pol_elt)
                policies.append(policy)
        return policies

    def _parse_routes(self, route_xml):
        log.info("parsing routes")
        sre = ET.parse(route_xml).getroot()
        routes = []
        # thanks for the namespaces, Juniper.
        for table in sre.findall('.//{http://xml.juniper.net/junos/12.1X44/junos-routing}route-table'):
            if table.findtext('{http://xml.juniper.net/junos/12.1X44/junos-routing}table-name') == 'inet.0':
                for rt_elt in table.findall('{http://xml.juniper.net/junos/12.1X44/junos-routing}rt'):
                    route = Route._from_xml(rt_elt)
                    if route:
                        routes.append(route)
                return routes
        return []

    def _parse_zones(self, configuration_security_zones_xml):
        log.info("parsing zones")
        scsze = ET.parse(configuration_security_zones_xml).getroot()
        zones = []
        for sz in scsze.findall('.//security-zone'):
            zones.append(Zone._from_xml(sz))
        return zones