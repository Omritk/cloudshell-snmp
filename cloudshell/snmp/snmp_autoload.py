"""
This module contains classes and utility functions to implement Quali resource manager Autoload
functionality using SNMP.
"""

import re

from quali_snmp import QualiSnmp
from collections import OrderedDict


class AutoLoad(object):
    """ Base class for Quali SNMP based Autoload functionality. """

    autolad_parents = {"'port'": ["'module'", "'chassis'"],
                       "'powerSupply'": ["'chassis'"],
                       "'module'": ["'chassis'"],
                       "'container'": ["'chassis'"],
                       "'chassis'": []}
    """ Dictionary mapping from autload entity to its valid autoload parents. """

    def __init__(self, snmp, logger):
        """ Initialize SNMP environment and read tables.

        Read entPhysicalTable and ifTable.
        entPhysicalTable is saved in self.entPhysicalTable
        ifTable is saved in self.ifTable

        :param ip: device IP.
        :param port: device SNMP port.
        :param community: device community.
        """
        super(AutoLoad, self).__init__()

        self.snmp = snmp
        self._logger = logger
        self._entPhysicalTable = None
        self._ifTable = None

    def get_table(self, snmp_module_name, table_name):
        self._logger.debug('\tReading \'{0}\' table from \'{1}\' ...'.format(table_name, snmp_module_name))
        ret_value = self.snmp.walk((snmp_module_name, table_name))
        self._logger.debug('\tDone.')
        return ret_value

    @property
    def entPhysicalTable(self):
        if self._entPhysicalTable is None:
            self._entPhysicalTable = self.get_table('ENTITY-MIB', 'entPhysicalTable')
        return self._entPhysicalTable

    @property
    def ifTable(self):
        if self._ifTable is None:
            self._ifTable = self.get_table('IF-MIB', 'ifTable')

        return self._ifTable



    def get_hierarchy(self, *types):
        """
        :return: device autoload hierarchy in the following format:
        |        {root index: [child1 index, child2 index, ...],
        |         child1 index: [child11 index, child12 index, ...]}
        |        ...}
        :todo: add support for multi chassis
        """

        hierarchy = {}
        ports = self.entPhysicalTable.filter_by_column('Class', "'port'")
        pss = self.entPhysicalTable.filter_by_column('Class', "'powerSupply'")
        for entity in dict(ports.items() + pss.items()).values():
            parents = self.get_parents(entity)
            for p in range(len(parents)-1, 0, -1):
                parent_index = int(parents[p]['suffix'])
                index = int(parents[p-1]['suffix'])
                if not hierarchy.get(parent_index):
                    hierarchy[parent_index] = []
                hierarchy[parent_index].append(index)
        for parent, childrenin in hierarchy.items():
            hierarchy[parent] = list(set(childrenin))
        return hierarchy

    def get_mapping(self):
        """ Get mapping from entPhysicalTable to ifTable.

        Build mapping based on entAliasMappingTable if exists else build manually based on
        entPhysicalDescr <-> ifDescr mapping.

        :return: simple mapping from entPhysicalTable index to ifTable index:
        |        {entPhysicalTable index: ifTable index, ...}
        """

        mapping = OrderedDict()
        entAliasMappingTable = self.snmp.walk(('ENTITY-MIB', 'entAliasMappingTable'))
        if entAliasMappingTable:
            for port in self.entPhysicalTable.filter_by_column('Class', "'port'"):
                entAliasMappingIdentifier = entAliasMappingTable[port]['entAliasMappingIdentifier']
                mapping[port] = int(entAliasMappingIdentifier.split('.')[-1])
        else:
            mapping = self._descr_based_mapping()

        return mapping

    #
    # Auxiliary public methods.
    #

    def get_parents(self, entity, *_parents):
        """
        :param entity: entity to return parents for.
        :return: autoload parents, up to the chassis, of the requested entity.
        """

        parents_l = list(_parents)
        parents_l.append(entity)
        if entity['entPhysicalClass'] == "'chassis'":
            return parents_l
        else:
            return self.get_parents(self.get_parent(entity), *parents_l)

    def get_parent(self, entity):
        """
        :param entity: entity to return parent for.
        :return: autoload parent of the requested entity.
        """

        parent = self.entPhysicalTable[int(entity['entPhysicalContainedIn'])]
        if parent['entPhysicalClass'] in self.autolad_parents[entity['entPhysicalClass']]:
            return parent
        else:
            return self.get_parent(parent)

    def _descr_based_mapping(self):
        """ Manually calculate mapping from entityTable to ifTable.

        :return: simple mapping from entPhysicalTable index to ifTable index:
        |        {entPhysicalTable index: ifTable index, ...}
        """

        mapping = OrderedDict()
        for port in self.entPhysicalTable.filter_by_column('Class', "'port'").values():
            entPhysicalDescr = port['entPhysicalDescr']
            module_index, port_index = re.findall('\d+', entPhysicalDescr)
            ifTable_re = '.*' + module_index + '/' + port_index
            for interface in self.ifTable.values():
                if re.search(ifTable_re, interface['ifDescr']):
                    mapping[int(port['suffix'])] = int(interface['suffix'])
                    continue
        return mapping
