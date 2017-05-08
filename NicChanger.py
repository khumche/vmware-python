#!/usr/bin/python
"""
Python test to change network interfaces on VM

by LovroG
"""

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl

import argparse
import atexit
import getpass
import ssl
import csv

def GetArgs():
    """
    Supports the command-line arguments listed below.
    """
    parser = argparse.ArgumentParser(
        description='NicChanger - a simple script that replaces all NICs with one listed in the CSV file.\n'
                    'The CSV should be in the following format: \n'
                    '"VMname", "MAC address", "Network name"')
    parser.add_argument('-s', '--host', required=True, action='store',
                        help='Remote host to connect to')
    parser.add_argument('-o', '--port', type=int, default=443, action='store',
                        help='Port to connect on. Defaults on 443')
    parser.add_argument('-u', '--user', required=True, action='store',
                        help='')
    parser.add_argument('-p', '--password', required=False, action='store',
                        help='')
    parser.add_argument('-f', '--file', required=True, action='store',
                        help='Filename containing CSV data')
    args = parser.parse_args()
    return args


def get_obj(content, vimtype, name):
    obj = None
    container = content.viewManager.CreateContainerView(
        content.rootFolder, vimtype, True)
    for c in container.view:
        if c.name == name:
            obj = c
            break
    return obj


def WaitForTasks(tasks, si):
    """
    Given the service instance si and tasks, it returns after all the
    tasks are complete
    """

    pc = si.content.propertyCollector

    taskList = [str(task) for task in tasks]

    # Create filter
    objSpecs = [vmodl.query.PropertyCollector.ObjectSpec(obj=task)
                for task in tasks]
    propSpec = vmodl.query.PropertyCollector.PropertySpec(type=vim.Task,
                                                          pathSet=[], all=True)
    filterSpec = vmodl.query.PropertyCollector.FilterSpec()
    filterSpec.objectSet = objSpecs
    filterSpec.propSet = [propSpec]
    filter = pc.CreateFilter(filterSpec, True)

    try:
        version, state = None, None

        # Loop looking for updates till the state moves to a completed state.
        while len(taskList):
            update = pc.WaitForUpdates(version)
            for filterSet in update.filterSet:
                for objSet in filterSet.objectSet:
                    task = objSet.obj
                    for change in objSet.changeSet:
                        if change.name == 'info':
                            state = change.val.state
                        elif change.name == 'info.state':
                            state = change.val
                        else:
                            continue

                        if not str(task) in taskList:
                            continue

                        if state == vim.TaskInfo.State.success:
                            # Remove task from taskList
                            taskList.remove(str(task))
                        elif state == vim.TaskInfo.State.error:
                            raise task.info.error
            # Move to next version
            version = update.version
    finally:
        if filter:
            filter.Destroy()


def enableNic(si, vm):

    """
    Attaches the "cable" and enables the NIC on the VM
    :param si: Service instance 
    :param vm: Virtual Machine Object
    :return: null, just does it's job...
    """

    virtual_nic_device = None
    for dev in vm.config.hardware.device:
        if isinstance(dev, vim.vm.device.VirtualEthernetCard):
            print "Found NIC, connecting and enabling " + dev.deviceInfo.label
            virtual_nic_device = dev
            virtual_nic_spec = vim.vm.device.VirtualDeviceSpec()
            virtual_nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
            virtual_nic_spec.device = virtual_nic_device
            virtual_nic_spec.device.key = virtual_nic_device.key
            virtual_nic_spec.device.macAddress = virtual_nic_device.macAddress
            virtual_nic_spec.device.backing = virtual_nic_device.backing
            virtual_nic_spec.device.wakeOnLanEnabled = virtual_nic_device.wakeOnLanEnabled
            connectable = vim.vm.device.VirtualDevice.ConnectInfo()
            connectable.connected = True
            connectable.startConnected = True
            virtual_nic_spec.device.connectable = connectable
            dev_changes = []
            dev_changes.append(virtual_nic_spec)
            spec = vim.vm.ConfigSpec()
            spec.deviceChange = dev_changes
            task = vm.ReconfigVM_Task(spec=spec)
            WaitForTasks({task}, si)


def removeNICs(si, vm):
    """
    Removes ALL NICs found on a VM instance
    :param si: Service instance 
    :param vm: Virtual Machine Object
    :return: 
    """
    virtual_nic_device = None
    for dev in vm.config.hardware.device:
        if isinstance(dev, vim.vm.device.VirtualEthernetCard):
            print "Found NIC, removing " + dev.deviceInfo.label
            virtual_nic_device = dev
            virtual_nic_spec = vim.vm.device.VirtualDeviceSpec()
            virtual_nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.remove
            virtual_nic_spec.device = virtual_nic_device
            virtual_nic_spec.device.key = virtual_nic_device.key
            virtual_nic_spec.device.macAddress = virtual_nic_device.macAddress
            virtual_nic_spec.device.backing = virtual_nic_device.backing
            virtual_nic_spec.device.wakeOnLanEnabled = virtual_nic_device.wakeOnLanEnabled
            connectable = vim.vm.device.VirtualDevice.ConnectInfo()
            virtual_nic_spec.device.connectable = connectable
            dev_changes = []
            dev_changes.append(virtual_nic_spec)
            spec = vim.vm.ConfigSpec()
            spec.deviceChange = dev_changes
            task = vm.ReconfigVM_Task(spec=spec)
            WaitForTasks({task}, si)


def addNic(si, vm, mac, network):
    """
    
    :param si: Service Instance
    :param vm: Virtual Machine Object
    :param network: Virtual Network name
    """
    spec = vim.vm.ConfigSpec()
    content = si.RetrieveContent()
    nic_changes = []

    portgroup = None
    portgroup = get_obj(content, [vim.dvs.DistributedVirtualPortgroup], network)
    if portgroup is None:
        print ("Portgroup " + network + " not Found in DVS ...")

    print ("Search Available(Unused) port for VM...")
    dvs = portgroup.config.distributedVirtualSwitch
    portKey = findPortId(dvs, portgroup.key)
    port = getPort(dvs, portKey)

    nic_spec = vim.vm.device.VirtualDeviceSpec()
    nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add

    nic_spec.device = vim.vm.device.VirtualVmxnet3()

    nic_spec.device.deviceInfo = vim.Description()
    nic_spec.device.deviceInfo.summary = 'Added by LovroG NICReplace script'

    nic_spec.device.backing = \
        vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo()
    nic_spec.device.backing.port = vim.dvs.PortConnection()
    nic_spec.device.backing.port.portgroupKey = port.portgroupKey
    nic_spec.device.backing.port.switchUuid = port.dvsUuid
    nic_spec.device.backing.port.portKey = port.key

    # nic_spec.device.backing.network = get_obj(content, [vim.Network], network)
    # nic_spec.device.backing.deviceName = network

    nic_spec.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
    nic_spec.device.connectable.connected = True
    nic_spec.device.connectable.status = 'ok'
    nic_spec.device.wakeOnLanEnabled = True
    nic_spec.device.addressType = 'manual'
    nic_spec.device.macAddress = mac
    nic_spec.device.connectable.startConnected = True
    nic_spec.device.connectable.allowGuestControl = True
    # print nic_spec.device.connectable

    nic_changes.append(nic_spec)
    spec.deviceChange = nic_changes
    task = vm.ReconfigVM_Task(spec=spec)
    WaitForTasks({task}, si)

    print "Network card added"


def findPortId(dvs, portgroupkey):
    search_portkey = []
    criteria = vim.dvs.PortCriteria()
    criteria.connected = False
    criteria.inside = True
    criteria.portgroupKey = portgroupkey
    ports = dvs.FetchDVPorts(criteria)
    for port in ports:
        search_portkey.append(port.key)
    print (search_portkey)
    return search_portkey[0]


def getPort(dvs, key):
    obj = None
    ports = dvs.FetchDVPorts()
    for c in ports:
        if c.key == key:
            obj = c
    return obj


def connect(args, targets):
    print "Connecting to the server..."
    try:

        context = None
        if hasattr(ssl, '_create_unverified_context'):
            context = ssl._create_unverified_context()
        si = SmartConnect(host=args.host,
                          user=args.user,
                          pwd=args.password,
                          port=int(args.port),
                          sslContext=context)
        if not si:
            print("Cannot connect to specified host using specified username and password")
            sys.exit()

        atexit.register(Disconnect, si)

        content = si.RetrieveContent()

        print "Starting work on VMs..."

        for row in targets:
            print "Working on " + row[0]
            vm = None
            vm = get_obj(content, [vim.VirtualMachine], row[0])

            if vm is None:
                print "VM " + row[0] + " not found..."

            removeNICs(si, vm)
            addNic(si, vm, row[1], row[2])
            enableNic(si, vm)


    except Exception as e:
        print("Caught Exception : " + str(e))


def main():
    args = GetArgs()

    if args.password:
        password = args.password
    else:
        args.password = getpass.getpass(prompt='Enter password for %s@%s'
                                               ': ' % (args.user, args.host))

    inputfile = open(args.file, "rb")
    csvreader = csv.reader(inputfile)
    connect(args, csvreader)

    return 0


if __name__ == "__main__":
    main()
