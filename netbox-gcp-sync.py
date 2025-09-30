
from    googleapiclient import discovery
from    google.oauth2 import service_account
import subprocess
import json
import  pynetbox
import confnetbox
import ipaddress
import logging
import datetime

# Generate timestamp
timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# Define log filename with timestamp
#Logging Function
log_filename = f"/var/log/netbox/netbox_{timestamp}.log"
logging.basicConfig(filename='netbox.log', level=logging.INFO)

# netbox connection
NETBOX_URL          = confnetbox.NETBOX_URL
TOKEN               = confnetbox.TOKEN
nb                  = pynetbox.api(url=NETBOX_URL, token=TOKEN)

# GCP connection
svc_account_key     = "/opt/netbox-scripts/svc_account.json"
credentials         = service_account.Credentials.from_service_account_file(svc_account_key)

# global variable to which IP VMs from GCP will be added - public and internal, which are NOT from default vpc
ip_from_gcp_list    = {"ip"  : [],}
# a global variable to which projects with a list of VMs with parameters to be added to netbox will be added
# format: instance_list_per_project = {project1: [{VM1},{VM2}], project2: [{VM1},{VM2}]}
instance_list_per_project = {}
# a global variable to which projects with a list of IPs, IPs that are not related to VM,
# format: rest_ip_from_gcp_list = {project1: [{ip1},{ip2}], project2: [{ip1},{ip2}]}

rest_ip_from_gcp_list = {}


cluster_group_name  = "gcp-organization"
cluster_type_name   = "gcp-project"

# creating a tag in netbox, this tag will be on all objects created with this script
tag_gcp_name        = "Aristocrat"
tag_gcp             = nb.extras.tags.get(name = tag_gcp_name)
# if the tag already exists, then we get its id, which we will use to add to other objects
if tag_gcp :
    tag_gcp_id      = tag_gcp.id
# if there is no tag, then we create it and get its id, which we will use to add to other objects
else:
    tag_gcp         = nb.extras.tags.create({"name": tag_gcp_name, "slug": tag_gcp_name})
    tag_gcp_id      = tag_gcp.id


#Netbox name of Tenant group of Organisation, We can provide tenant as GCP Project ID, 
tenant_group_name= "GCPProjects"
if nb.tenancy.tenant_groups.filter(name= tenant_group_name):
    tenant_group = nb.tenancy.tenant_groups.get(name= tenant_group_name)
    tenant_group.tags.append(tag_gcp_id)
    tenant_group.save()
    tenant_groupid = tenant_group.id
else:
    tenant_group = nb.tenancy.tenant_groups.create({"name": tenant_group_name, "slug": tenant_group_name, "tags":[{"name":tag_gcp_name, "slug":tag_gcp_name}]})
    tenant_groupid = tenant_group.id


# netbox name of the cluster group and the type of clusters. each project will be equal to a cluster in netbox

dns = discovery.build('dns', 'v1', credentials=credentials)

# Function to list all DNS zones in a project
def list_dns_zones(project_id):
    zones = dns.managedZones().list(project=project_id).execute()
    return zones.get('managedZones', [])

# Function to list all DNS records in a zone
def list_dns_records(project_id, zone_name):
    records = dns.resourceRecordSets().list(
        project=project_id,
        managedZone=zone_name
    ).execute()
    return records.get('rrsets', [])

# Function to filter records containing an IP address
def filter_ip_records(records):
    ip_records = []
    for record in records:
        if record['type'] in ['A', 'AAAA']:
            ip_records.append(record)
    return ip_records

# Main function to get IP records for all zones in a project
def get_ip_records_for_zones(project_id, tenant):
    zones = list_dns_zones(project_id)
    for zone in zones:
        zone_name = zone['name']
        print(f"Zone: {zone_name}")
        records = list_dns_records(project_id, zone_name)
        ip_records = filter_ip_records(records)
        for record in ip_records:
            print(f"Record: {record['name']} - {record['type']} - {record['ttl']} - {record['rrdatas']}")
            if nb.ipam.ip_addresses.filter(address = record['rrdatas'][0], tenant_id = tenant):
                ip_nb               = nb.ipam.ip_addresses.get(address = record['rrdatas'][0], tenant_id = tenant)
                ip_nb.dns_name      = record['name']
                ip_nb.save()

# a function that returns a list of projects that have the compute API enabled, so as not to make invalid requests to find VMs in projects (if the API is not enabled, then the requests will fail).
def Get_project_list(projects_i_want):
    # Only consider projects from the predefined list
    projects_list_compute_enabled = []

    for project_id in projects_i_want:
        # connect to GCP and get a list of all enabled services on the project
    
        # by default, we assume that the Compute API is disabled
        COMPUTEAPI = "YES"

        # if Compute API is enabled, add the project to the list
        if COMPUTEAPI == "YES":
            projects_list_compute_enabled.append(project_id)

    return projects_list_compute_enabled

def netbox_tenant_create(project_id):
    ### Tenant group
    # If same tenant group exists 
    if nb.tenancy.tenants.filter(name= project_id):
        tenant = nb.tenancy.tenants.get(name = project_id)
        tenant.tags.append(tag_gcp_id)
        tenant.save()
        tenant = tenant.id
    else:
        tenant = nb.tenancy.tenants.create({"name": project_id, "slug": project_id, "group": tenant_groupid, "tags":[{"name":tag_gcp_name, "slug":tag_gcp_name}]})
        tenant = tenant.id

    return tenant
# create clusters in netbox, cluster == project.

def netbox_cluster_create(project_id):
    #### cluster group
    # if such a cluster group already exists, then update the tag and get the id
    if nb.virtualization.cluster_groups.filter(name= cluster_group_name):
        cluster_group       = nb.virtualization.cluster_groups.get(name = cluster_group_name)
        cluster_group.tags.append(tag_gcp_id)
        cluster_group.save()
        cluster_group_id    = cluster_group.id
    # if there is no cluster group, then create and get id
    else:
        cluster_group       = nb.virtualization.cluster_groups.create({"name": cluster_group_name, "slug": cluster_group_name, "tags":[{"name":tag_gcp_name, "slug":tag_gcp_name}]})
        cluster_group_id    = cluster_group.id

    ### cluster type
    # if this cluster type already exists, then update the tag and get its id
    if nb.virtualization.cluster_types.filter(name= cluster_type_name):
        cluster_type        = nb.virtualization.cluster_types.get(name= cluster_type_name)
        cluster_type.tags.append(tag_gcp_id)
        cluster_type.save()
        cluster_type_id     = cluster_type.id
    # if there is no cluster type, then create and get its id
    else:
        cluster_type        = nb.virtualization.cluster_types.create({"name": cluster_type_name, "slug": cluster_type_name, "tags":[{"name":tag_gcp_name, "slug":tag_gcp_name}]})
        cluster_type_id     = cluster_type.id
    # ### add clusters == projects
    # # get a list of all projects from an organization
    # service_project         = discovery.build('cloudresourcemanager', 'v1', credentials=credentials)
    # request_project         = service_project.projects().list()
    # response_project        = request_project.execute()
    # project_list            = response_project['projects']
    # project_list_from_gcp   = []
    # for project in project_list:
    #     project_name        = project["projectId"]
    #     project_list_from_gcp.append(project_name)
    #     # if such a cluster already exists, then update its group, type and tag in case they are out of date
    #     if nb.virtualization.clusters.filter(name = project_name):
    #         cluster         = nb.virtualization.clusters.get(name = project_name)
    #         cluster.type    = cluster_type_id
    #         cluster.group   = cluster_group_id
    #         cluster.tags.append(tag_gcp_id)
    #         cluster.save()
    #     # if there is no cluster, then create it and add the necessary group and type
    #     else:
    #         data_clusters   = {"name": project_name, "slug": project_name, "type" : cluster_type_id, "group" : cluster_group_id, "tags" : [{"name" : tag_gcp_name, "slug" : tag_gcp_name}]}
    #         nb.virtualization.clusters.create(**data_clusters)
    # return(project_list_from_gcp)
    if nb.virtualization.clusters.filter(name = project_id):
            cluster         = nb.virtualization.clusters.get(name = project_id)
            cluster.type    = cluster_type_id
            cluster.group   = cluster_group_id
            cluster.tags.append(tag_gcp_id)
            cluster.save()
        # if there is no cluster, then create it and add the necessary group and type
    else:
        data_clusters   = {"name": project_id, "slug": project_id, "type" : cluster_type_id, "group" : cluster_group_id, "tags" : [{"name" : tag_gcp_name, "slug" : tag_gcp_name}]}
        nb.virtualization.clusters.create(**data_clusters)  

# add data to global variables ip_from_gcp_list and ip_from_gcp_list. Up-to-date data on IP and VM
def Get_response_instances_from_project(project_id):
    # GCP connection
    service_compute = discovery.build('compute', 'v1', credentials=credentials)
    request         = service_compute.instances().aggregatedList(project=project_id)
    response        = request.execute()["items"].items()

    # an empty list to which VMs with parameters will be added

    instance_list   = []

    # we get set in response, in for will have two required parameters
    for zone, instances in response:
        # parameters are returned for all zones, we are only interested in where the VM is
        if "instances" in instances.keys():
            # create a list of VMs, write only the parameters we need
            for instance in instances["instances"]:
                data_instance = {}

                # VM name
                data_instance["name"] = instance.get("name")

                # VM status
                if instance["status"] == "RUNNING":
                    STATUS  = "active"
                else:
                    STATUS  = "offline"
                data_instance["status"] = STATUS

                # interfaces
                if "networkInterfaces" in instance.keys():
                    for intf in instance["networkInterfaces"]:
                        # if VPC NOT default, then find Internal ip
                        if intf["network"].split("/")[-1] == "default":
                            pass
                        else:
                            ip_int                          = intf["networkIP"]
                            data_instance["ip_internal"]    = ip_int
                            # add IP in global var
                            ip_from_gcp_list["ip"].append(ip_int)
                        # external IP
                        if "accessConfigs" in intf.keys():
                            dict_accessConfigs = intf["accessConfigs"][0]
                            if "natIP" in dict_accessConfigs:
                                ip_ext                          = dict_accessConfigs["natIP"]
                                data_instance["ip_external"]    = ip_ext
                                # add IP in global var
                                ip_from_gcp_list["ip"].append(ip_ext)
                data_instance["os-type"]=instance['disks'][0]['licenses'][0].split('/')[-1]
                # disk size. summ all disks
                if "disks" in instance.keys():
                    summ_all_disks = 0
                    for disk in instance["disks"]:
                        summ_all_disks += int(disk["diskSizeGb"])
                    data_instance["disk"] = summ_all_disks

                # CPU and RAM
                if "machineType" in instance.keys():
                    instance_machine_type   = instance["machineType"].split("/")[-1]
                    request_machine_type    = service_compute.machineTypes().get(project=project_id, zone=zone.split("/")[-1], machineType=instance_machine_type)
                    response_machine_type   = request_machine_type.execute()
                    data_instance["memory"] = response_machine_type["memoryMb"]
                    data_instance["vcpus"]  = response_machine_type["guestCpus"]

                # add data for one VM to the VM list
                instance_list.append(data_instance)

    # add a list of VMs to a global variable with a dictionary for each project
    instance_list_per_project[project_id] = instance_list

def get_network_info(project_id, tenant):
    service_compute = discovery.build('compute', 'v1', credentials=credentials)
    
    # Get a list of all networks
    networks_request = service_compute.networks().list(project=project_id)
    networks_response = networks_request.execute()
    networks = networks_response.get("items", [])

    # Get a list of all subnets
    subnets_request = service_compute.subnetworks().list(project=project_id, region='us-central1')  # Replace 'your-region' with your actual region
    subnets_response = subnets_request.execute()
    subnets = subnets_response.get("items", [])

    # Print network information
    for network in networks:
        #Create VRFs
        # Get or create VRF based on project_id
        #Get Tenant ID
        vpc_name = f"{network['name']}"
        print(f"{vpc_name}")
        vpc = nb.ipam.vrfs.get(name=vpc_name, tenant_id=tenant)
        if not vpc:
            vpc = nb.ipam.vrfs.create({"name": vpc_name, "tenant": tenant, "tags":[{"name":tag_gcp_name, "slug":tag_gcp_name}]})     
        for subnet in subnets:
            # Create Aggregate
            if subnet['network'].split("/")[-1] == vpc_name:
                prefix_name = f"{subnet['name']}"
                data_new_prefix = {
                    "prefix" : subnet['ipCidrRange'],
                    "status" : "active",
                    "vrf"    : vpc.id,
                    "tenant" : tenant, 
                    "is_pool": "true",
                }
                if nb.ipam.prefixes.filter(prefix=subnet['ipCidrRange'] , vrf_id = vpc.id):
                    prefix = nb.ipam.prefixes.get(prefix=subnet['ipCidrRange'], vrf_id = vpc.id)
                    prefix.tenant = tenant
                    prefix.save()
                else:
                    # if nb.ipam.prefixes.filter(prefix=subnet['ipCidrRange'], tenant_id = tenant):
                    #     prefix = nb.ipam.prefixes.get(prefix=subnet['ipCidrRange'], tenant_id = tenant)
                    #     prefix.delete()
                    # else:
                    nb.ipam.prefixes.create(**data_new_prefix)

def netbox_ip_to_prefix(ip_addr, tenant):
    prefix_range = nb.ipam.prefixes.filter(tenant_id = tenant)

    for range in prefix_range:
        iprange = range.display
        if ipaddress.ip_address(ip_addr) in ipaddress.ip_network(iprange):
            return range
    
    return None
# create VM and IP in netbox
def netbox_vm_create(project_id, data_instance):
    #Introducing tenant id, 
    tenant = netbox_tenant_create(project_id)

    # VM parameters
    cluster         = nb.virtualization.clusters.get(name = project_id)
    cluster_id      = cluster.id
    name_vm         = data_instance["name"]
    status_vm       = data_instance["status"]
    disk_vm         = data_instance["disk"]
    memory_vm       = data_instance["memory"]
    vcpus_vm        = data_instance["vcpus"]
    os_vm           = data_instance["os-type"]
    # interfaces will always be created with the same name
    nic_internal    = "nic-internal"
    nic_external    = "nic-external"
    
    # new VM parameters
    data_new_vm     = {
        "name"      : name_vm,
        "status"    : status_vm,
        "cluster"   : cluster_id,
        "disk"      : disk_vm,
        "memory"    : memory_vm,
        "vcpus"     : vcpus_vm,
        "tenant"    : tenant, 
        "tags"      : [{"name":tag_gcp_name, "slug":tag_gcp_name}],
        "custom_fields" : {"Operating_System": os_vm}
        }

    # if the VM already exists, then we update its parameters in case they are out of date, and we get the id. Because there may be VMs with the same names, then we are looking for in a specific cluster
    if nb.virtualization.virtual_machines.filter(name = name_vm, cluster = project_id):
        vm          = nb.virtualization.virtual_machines.get(name = name_vm, cluster = project_id)
        vm.status   = status_vm
        vm.disk     = disk_vm
        vm.memory   = memory_vm
        vm.vcpus    = vcpus_vm
        vm.tags.append(tag_gcp_id)
        vm.tenant   = tenant
        vm.custom_fields["Operating_System"] = os_vm
        vm.save()
        vm_id       = vm.id
    # if there is no VM, then we create it and get the id
    else:
        vm_new  = nb.virtualization.virtual_machines.create(**data_new_vm)
        vm_id   = vm_new.id
    
    # updating or creating internal interfaces
    if nb.virtualization.interfaces.filter(name = nic_internal, virtual_machine_id = vm_id):
        interface_internal_vm       = nb.virtualization.interfaces.get(name = nic_internal, virtual_machine_id = vm_id)
        interface_internal_vm.tags.append(tag_gcp_id)
        interface_internal_vm.save()
        interface_internal_vm_id    = interface_internal_vm.id
    else:
        data_interface_internal_vm  = {"name" : nic_internal, "virtual_machine" : vm_id, "tags" :[{"name":tag_gcp_name, "slug":tag_gcp_name}]}
        interface_internal_vm       = nb.virtualization.interfaces.create(**data_interface_internal_vm)
        interface_internal_vm_id    = interface_internal_vm.id

    # updating or creating external interfaces
    if nb.virtualization.interfaces.filter(name = nic_external, virtual_machine_id = vm_id):
        interface_external_vm       = nb.virtualization.interfaces.get(name = nic_external, virtual_machine_id = vm_id)
        interface_external_vm.tags.append(tag_gcp_id)
        interface_external_vm.save()
        interface_external_vm_id    = interface_external_vm.id
    else:
        data_interface_external_vm  = {"name" : nic_external, "virtual_machine" : vm_id, "tags" :[{"name":tag_gcp_name, "slug":tag_gcp_name}]}
        interface_external_vm       = nb.virtualization.interfaces.create(**data_interface_external_vm)
        interface_external_vm_id    = interface_external_vm.id

    # if there is an internal IP not from the default vpc in the VM parameters, then we create this IP and attach it to the VM
    if "ip_internal" in data_instance.keys():
        ip_internal                 = data_instance["ip_internal"]
        prefix = netbox_ip_to_prefix(ip_internal, tenant)
        ip_nb=0 
        if prefix is None:
            data_ip_internal_address    = {
                "address"               : ip_internal,
                "assigned_object_type"  : "virtualization.vminterface",
                "assigned_object_id"    : interface_internal_vm_id,
                "tenant"                : tenant,
                "tags"                  : [{"name":tag_gcp_name, "slug":tag_gcp_name}],
                "custom_fields"         : {"hostname": data_instance["name"]}
            }
            print(f"{ip_internal}")
            
            if nb.ipam.ip_addresses.filter(address = ip_internal, tenant_id = tenant):
                ip_nb                           = nb.ipam.ip_addresses.get(address = ip_internal, tenant_id = tenant)            
                ip_nb.assigned_object_type      = "virtualization.vminterface"
                ip_nb.assigned_object_id        = interface_internal_vm_id
                ip_nb.tags.append(tag_gcp_id)
                ip_nb.tenant                    = tenant
                ip_nb.custom_fields["hostname"] = data_instance["name"]
                ip_nb.save()
                ip_nb = ip_nb.id
            else:
                nb.ipam.ip_addresses.create(**data_ip_internal_address)
            
        else:
            vpc_id = prefix.vrf.id
            data_ip_internal_address    = {
                    "address"               : ip_internal,
                    "assigned_object_type"  : "virtualization.vminterface",
                    "assigned_object_id"    : interface_internal_vm_id,
                    "tenant"                : tenant,
                    "tags"                  : [{"name":tag_gcp_name, "slug":tag_gcp_name}],
                    "custom_fields"         : {"hostname": data_instance["name"]},
                    "vrf"                   : prefix.vrf.id

                }
            print(f"{ip_internal}")
                
            if nb.ipam.ip_addresses.filter(address = ip_internal, tenant_id = tenant, vrf_id = prefix.vrf.id):
                try:
                    ip_nb                           = nb.ipam.ip_addresses.get(address = ip_internal, tenant_id = tenant, vrf_id = prefix.vrf.id)            
                    ip_nb.assigned_object_type      = "virtualization.vminterface"
                    ip_nb.assigned_object_id        = interface_internal_vm_id
                    ip_nb.tags.append(tag_gcp_id)
                    ip_nb.tenant                    = tenant
                    ip_nb.custom_fields["hostname"] = data_instance["name"]
                    ip_nb.save()
                    ip_nb = ip_nb.id
                except:
                    print("Cannot reassign IP address while it is designated as the primary IP for the parent object")
            else:
                ip_nb = nb.ipam.ip_addresses.create(**data_ip_internal_address)
                ip_nb = ip_nb.id
        # Add primary ip to VM
        try:    
            print(f"{ip_internal}")
            vm_primary_ip = nb.virtualization.virtual_machines.get(name=name_vm, cluster=project_id)
            vm_primary_ip.primary_ip4 = {"id": ip_nb }
            vm_primary_ip.save()
        except:
            print(f" error add primary IP to VM {name_vm}")
    else:
        pass
    
    # if there is a public IP in the VM parameters, then we create this IP and attach it to the VM
    if "ip_external" in data_instance.keys():
        ip_external                 = data_instance["ip_external"]
        prefix = netbox_ip_to_prefix(ip_external, tenant)
        if prefix is None:
            data_ip_external_address    = {
                "address"               : ip_external,
                "assigned_object_type"  : "virtualization.vminterface",
                "assigned_object_id"    : interface_external_vm_id,
                "tenant"                : tenant,
                "custom_fields"         : {"hostname": data_instance["name"]},
                "tags"                  : [{"name":tag_gcp_name, "slug":tag_gcp_name}],
            }

            if nb.ipam.ip_addresses.filter(address = ip_external, tenant_id = tenant):
                ip_nb                           = nb.ipam.ip_addresses.get(address = ip_external, tenant_id = tenant)
                ip_nb.assigned_object_type      = "virtualization.vminterface"
                ip_nb.assigned_object_id        = interface_external_vm_id
                ip_nb.tenant                    = tenant
                ip_nb.custom_fields["hostname"] = data_instance["name"]
                ip_nb.tags.append(tag_gcp_id)
                ip_nb.save()
        else:
            vpc_id = prefix.vrf.id
            data_ip_external_address    = {
                "address"               : ip_external,
                "assigned_object_type"  : "virtualization.vminterface",
                "assigned_object_id"    : interface_external_vm_id,
                "tenant"                : tenant,
                "custom_fields"         : {"hostname": data_instance["name"]},
                "tags"                  : [{"name":tag_gcp_name, "slug":tag_gcp_name}],
                "vrf"                   : vpc_id
            }
        
            if nb.ipam.ip_addresses.filter(address = ip_external, tenant_id = tenant, vrf_id = vpc_id):
                ip_nb                           = nb.ipam.ip_addresses.get(address = ip_external, tenant_id = tenant, vrf_id = vpc_id)
                ip_nb.assigned_object_type      = "virtualization.vminterface"
                ip_nb.assigned_object_id        = interface_external_vm_id
                ip_nb.tenant                    = tenant
                ip_nb.custom_fields["hostname"] = data_instance["name"]
                ip_nb.tags.append(tag_gcp_id)
                ip_nb.save()
            else:
                nb.ipam.ip_addresses.create(**data_ip_external_address)
    else:
        pass
    # Use gcloud command to list all IP addresses in the specified GCP project

def netbox_rest_ip(project_id,tenant):
    compute = discovery.build('compute', 'v1', credentials=credentials) 
    ip_addresses = []

    # List all global IP addresses
    global_request = compute.globalAddresses().list(project=project_id) 
    global_response = global_request.execute() 
    global_addresses = global_response.get('items', [])
    ip_addresses.extend(global_addresses)

    # List IP addresses for each region
    regions_request = compute.regions().list(project=project_id)
    regions_response = regions_request.execute()
    for region_item in regions_response['items']:
        region_name = region_item['name']
        region_request = compute.addresses().list(project=project_id, region=region_name)
        region_response = region_request.execute() 
        region_addresses = region_response.get('items', [])
        if region_addresses:
            ip_addresses.extend(region_addresses)
# Now ip_addresses contains IP addresses from all regions
    rest_ip_addresses = []
    for ip_address in ip_addresses:
        ip_rest = ip_address['address']
        rest_ip_addresses.append(ip_rest)
        prefix = netbox_ip_to_prefix(ip_rest, tenant)
        if prefix is None:
            if nb.ipam.ip_addresses.filter(address = ip_address['address'],tenant_id = tenant):
                ip_nb = nb.ipam.ip_addresses.get(address = ip_address['address'], tenant_id= tenant)
                ip_nb.tenant    = tenant
                ip_nb.custom_fields["hostname"] = ip_address['name']
                ip_nb.tags.append(tag_gcp_id)
                ip_nb.save()
            else:
                nb.ipam.ip_addresses.create({
                    "address"               : ip_address['address'],
                    "tenant"                : tenant,
                    "tags"                  : [{"name":tag_gcp_name, "slug":tag_gcp_name}],
                    "custom_fields"         : {"hostname": ip_address['name']}
                })
        else:
            vpc_id = prefix.vrf.id
            if nb.ipam.ip_addresses.filter(address = ip_address['address'],tenant_id = tenant, vrf_id = vpc_id):
                ip_nb = nb.ipam.ip_addresses.get(address = ip_address['address'], tenant_id= tenant, vrf_id = vpc_id)
                ip_nb.tenant    = tenant
                ip_nb.custom_fields["hostname"] = ip_address['name']
                ip_nb.tags.append(tag_gcp_id)
                ip_nb.save()
            else:
                nb.ipam.ip_addresses.create({
                    "address"               : ip_address['address'],
                    "tenant"                : tenant,
                    "tags"                  : [{"name":tag_gcp_name, "slug":tag_gcp_name}],
                    "custom_fields"         : {"hostname": ip_address['name']},
                    "vrf"                   : vpc_id
                })
    rest_ip_from_gcp_list[project_id] = rest_ip_addresses
    # We need to pass private IPs not assigned to any VM as well

# delete obsolete clusters (projects), VM and IP
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
            if "ip_external" in instance.keys():
                ip_list_from_gcp.append(instance["ip_external"])
        try:
            ip_list_from_gcp.extend(rest_ip_from_gcp_list[project])
        except Exception as e:
            print(f"An error occurred for {project}: {e}")
            
        print(f"IP List for Project {project}: {ip_list_from_gcp}")
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
        ip = str(ip).split("/")[0]
        ip_list_from_netbox.append(ip)
    # compare lists and get those objects from netbox that do not match the current request from GCP
    list_project_difference = list(set(project_from_netbox) - set(projects_i_want))
    list_vm_difference      = list(set(instance_list_from_netbox) - set(instance_list_from_gcp))
    list_ip_difference      = list(set(ip_list_from_netbox) - set(ip_list_from_gcp))

    for vm in list_vm_difference:
        try:
            del_vm = nb.virtualization.virtual_machines.get(name=vm, tag=tag_gcp_name)
            del_vm.delete()
        except Exception as e:
            logging.error(f"Error deleting VM {vm}: {e}")

    for ip in list_ip_difference:
        try:
            del_ip = nb.ipam.ip_addresses.get(address=ip, tenant_group_id = tenant_groupid)
            del_ip.delete()
        except Exception as e:
            logging.error(f"Error deleting IP {ip}: {e}")
    for cluster in list_project_difference:
        try:
            del_cluster = nb.virtualization.clusters.get(name=cluster)
            del_cluster.delete()
        except Exception as e:
            logging.error(f"Error deleting cluster {cluster}: {e}")


def main():
    # create cluster group, cluster type and clusters
    
    projects_i_want = confnetbox.projects

    for project_id in projects_i_want:
        print(f"***********Creating {project_id} Cluster***********")
        netbox_cluster_create(project_id)
        logging.info(f"Successfully created {project_id} Cluster")
        print(f"***********Creating {project_id} teanant***********")
        logging.info(f"Successfully created {project_id} tenant")
        tenant= netbox_tenant_create(project_id)
        print(f"***********Getting {project_id} network info***********")
        try:
            get_network_info(project_id,tenant)
            logging.info(f"Successfully retrieved network info for {project_id}")
        except Exception as e:
            logging.error(f"An error occurred for {project_id}: {e}", exc_info=True)
        # we get the VM parameters for each project, add them to the global variable. We get internal IPs not from default vpc and public ip
        print(f"***********Getting VM Instances for {project_id}***********")
        try:
            Get_response_instances_from_project(project_id)
            logging.info(f"Successfully retrieved VM instances for {project_id}")
        except Exception as e:
            logging.error(f"An error occurred for {project_id}: {e}", exc_info=True)
        print(f"***********Getting remaining IPs for {project_id}***********")
        try:
            netbox_rest_ip(project_id,tenant)
            logging.info(f"Successfully retrieved remaining IPs for {project_id}")
        except Exception as e:
            logging.error(f"An error occurred: {e}", exc_info=True)
        print(f"***********Getting A DNS records for {project_id} ***********")
        #Checking if Project has DNS enabled or not
        service = discovery.build('serviceusage', 'v1')
        request = service.services().get(name=f"projects/{project_id}/services/dns.googleapis.com")
        response = request.execute()
        if response.get('state') == 'DISABLED':
            logging.info(f"DNS API is disable for {project_id}")
        else:
            try:
                get_ip_records_for_zones(project_id, tenant)
            except Exception as e:
                logging.error(f"An error occurred for {project_id}: {e}") 
        instance_list = instance_list_per_project[project_id]
        print(f"***********Creating VMs for {project_id}***********")
        for data_instance in instance_list:
            print(f"Instance Name: {data_instance['name']}")
            try:
                netbox_vm_create(project_id, data_instance)
                logging.info(f"VM  {data_instance['name']} created inside {project_id}")
            except Exception as e:
                logging.error(f"An error occurred for {data_instance['name']} inside {project_id}: {e}")
    #delete irrelevant information from netbox
    logging.info(f"***********Cleaning Netbox***********")
    delete_from_netbox(projects_i_want,instance_list_per_project, rest_ip_from_gcp_list)
        

if __name__ == "__main__" :
    main()
