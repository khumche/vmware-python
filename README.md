# vmware-python
Some basic python based VMWare administration scripts

NicChanger.py - network card swapping script

# Requirements
python 2.6+
http://vmware.github.io/pyvmomi-community-samples/

# NicChanger.py
Based on available sample scripts from 
https://github.com/vmware/pyvmomi

The script takes a CSV file with rows in the following format
"vmName,ma:ca:dd:re:ss,NetworkName"

After it connects to the vCenter or ESX host, tries to find the VMs, removes ALL the network interfaces currently used on the VM and creates a new Vmxnet3 interface with the given MAC address and connects it to the specified network on the vSwtich

