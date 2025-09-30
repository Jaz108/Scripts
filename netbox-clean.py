from    googleapiclient import discovery
from    google.oauth2 import service_account
import subprocess
import json
import  pynetbox
import confnetbox
import ipaddress
# netbox connection
NETBOX_URL          = confnetbox.NETBOX_URL
TOKEN               = confnetbox.TOKEN
nb                  = pynetbox.api(url=NETBOX_URL, token=TOKEN)

# GCP connection
svc_account_key     = "/tmp/netbox-scripts/svc_account.json"
credentials         = service_account.Credentials.from_service_account_file(svc_account_key)

def delete_from_netbox(projects_i_want,instance_list_per_project,rest_ip_from_gcp_list):
    instance_list_from_gcp      = []
    ip_list_from_gcp            = []
    project_from_netbox         = []
    instance_list_from_netbox   = []
    ip_list_from_netbox         = []

     # from the global variable instance_list_per_project we get a list of VMs and IPs from GCP
    for project in instance_list_per_project.keys():
        instance_list = instance_list_per_project[project]
        for instance in instance_list:
            instance_list_from_gcp.append(instance["name"])
            if "ip_internal" in instance.keys():
                ip_list_from_gcp.append(instance["ip_internal"])
            else:
                None
            if "ip_external" in instance.keys():
                ip_list_from_gcp.append(instance["ip_external"])
            else:
                None
        ip_list_from_gcp.extend(rest_ip_from_gcp_list[project])
    # get clusters (projects), VM and IP from netbox
    response_tenants_from_netbox = nb.tenancy.tenants.filter(tenant__n = tenant_group_name)
    for project in response_tenants_from_netbox:
        project_from_netbox.append(str(project))
    response_vm_from_netbox =  nb.virtualization.virtual_machines.filter(tenant__n = tenant_group_name)
    for instance in response_vm_from_netbox:
        instance_list_from_netbox.append(str(instance))
    response_ip_from_netbox =  nb.ipam.ip_addresses.filter(tenant__n = tenant_group_name)
    for ip in response_ip_from_netbox:
        # from netbox we get ip with a mask, remove it, because from GCP we receive without a mask. There must be one format for comparison
        ip_list_from_netbox.append(str(ip).split("/")[0])
    # compare lists and get those objects from netbox that do not match the current request from GCP
    list_project_difference = list(set(project_from_netbox) - set(projects_i_want))
    list_vm_difference      = list(set(instance_list_from_netbox) - set(instance_list_from_gcp))
    list_ip_difference      = list(set(ip_list_from_netbox) - set(ip_list_from_gcp))

    try:    
        for vm in list_vm_difference:
            del_vm = nb.virtualization.virtual_machines.get(name=vm, tag = tag_gcp_name)
            del_vm.delete()
    except:
        None

    try:    
        for ip in list_ip_difference:
            del_ip = nb.ipam.ip_addresses.get(address=ip)
            del_ip.delete()
    except:
        None

    try:    
        for cluster in list_project_difference:
            del_cluster = nb.virtualization.clusters.get(name=cluster)
            del_cluster.delete()
    except:
        None
def main():
    projects_i_want = confnetbox.projects
