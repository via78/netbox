import logging

from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver

from .choices import CableEndChoices, LinkStatusChoices
from .models import (
    Cable, CablePath, CableTermination, Device, FrontPort, PathEndpoint, PowerPanel, Rack, Location, VirtualChassis,
)
from .models.cables import trace_paths
from .utils import create_cablepath, rebuild_paths


#
# Location/rack/device assignment
#

@receiver(post_save, sender=Location)
def handle_location_site_change(instance, created, **kwargs):
    """
    Update child objects if Site assignment has changed. We intentionally recurse through each child
    object instead of calling update() on the QuerySet to ensure the proper change records get created for each.
    """
    if not created:
        instance.get_descendants().update(site=instance.site)
        locations = instance.get_descendants(include_self=True).values_list('pk', flat=True)
        Rack.objects.filter(location__in=locations).update(site=instance.site)
        Device.objects.filter(location__in=locations).update(site=instance.site)
        PowerPanel.objects.filter(location__in=locations).update(site=instance.site)


@receiver(post_save, sender=Rack)
def handle_rack_site_change(instance, created, **kwargs):
    """
    Update child Devices if Site or Location assignment has changed.
    """
    if not created:
        Device.objects.filter(rack=instance).update(site=instance.site, location=instance.location)


#
# Virtual chassis
#

@receiver(post_save, sender=VirtualChassis)
def assign_virtualchassis_master(instance, created, **kwargs):
    """
    When a VirtualChassis is created, automatically assign its master device (if any) to the VC.
    """
    if created and instance.master:
        master = Device.objects.get(pk=instance.master.pk)
        master.virtual_chassis = instance
        master.vc_position = 1
        master.save()


@receiver(pre_delete, sender=VirtualChassis)
def clear_virtualchassis_members(instance, **kwargs):
    """
    When a VirtualChassis is deleted, nullify the vc_position and vc_priority fields of its prior members.
    """
    devices = Device.objects.filter(virtual_chassis=instance.pk)
    for device in devices:
        device.vc_position = None
        device.vc_priority = None
        device.save()


#
# Cables
#

def termination_in_path(terminations, instance):
    if terminations and isinstance(terminations[0], PathEndpoint):
        if CablePath.objects.filter(_nodes__contains=instance).filter(_nodes__contains=terminations[0]):
            return True

    return False


def create_or_rebuild_paths(nodes, in_path):
    if not nodes:
        return

    if isinstance(nodes[0], PathEndpoint):
        if in_path:
            print(f"rebuild_paths1 for: {nodes}")
            rebuild_paths(nodes, True)
        else:
            print(f"create_cablepath for: {nodes}")
            create_cablepath(nodes)
    else:
        print(f"rebuild_paths2 for: {nodes}")
        rebuild_paths(nodes)


@receiver(trace_paths, sender=Cable)
def update_connected_endpoints(instance, created, raw=False, **kwargs):
    """
    When a Cable is saved with new terminations, retrace any affected cable paths.
    """
    print("update_connected_endpoints")
    logger = logging.getLogger('netbox.dcim.cable')
    if raw:
        logger.debug(f"Skipping endpoint updates for imported cable {instance}")
        return

    # Update cable paths if new terminations have been set
    if instance._terminations_modified:
        a_terminations = []
        b_terminations = []
        for t in instance.terminations.all():
            if t.cable_end == CableEndChoices.SIDE_A:
                a_terminations.append(t.termination)
            else:
                b_terminations.append(t.termination)

        print(f"a_terminations: {a_terminations}")
        print(f"b_terminations: {b_terminations}")
        a_terminations_in_path = termination_in_path(a_terminations, instance)
        b_terminations_in_path = termination_in_path(b_terminations, instance)

        create_or_rebuild_paths(a_terminations, a_terminations_in_path)
        create_or_rebuild_paths(b_terminations, b_terminations_in_path)

    # Update status of CablePaths if Cable status has been changed
    elif instance.status != instance._orig_status:
        if instance.status != LinkStatusChoices.STATUS_CONNECTED:
            CablePath.objects.filter(_nodes__contains=instance).update(is_active=False)
        else:
            rebuild_paths([instance])


@receiver(post_delete, sender=Cable)
def retrace_cable_paths(instance, **kwargs):
    """
    When a Cable is deleted, check for and update its connected endpoints
    """
    print("retrace_cable_paths")
    for cablepath in CablePath.objects.filter(_nodes__contains=instance):
        cablepath.retrace()


@receiver(post_delete, sender=CableTermination)
def nullify_connected_endpoints(instance, **kwargs):
    """
    Disassociate the Cable from the termination object, and retrace any affected CablePaths.
    """
    print("nullify_connected_endpoints")
    model = instance.termination_type.model_class()
    model.objects.filter(pk=instance.termination_id).update(cable=None, cable_end='')

    # for cablepath in CablePath.objects.filter(_nodes__contains=instance.cable):
    #     print(f"_nodes before: {cablepath._nodes}")
    #     cablepath._nodes.remove(instance)
    #     print(f"_nodes after: {cablepath._nodes}")
    #     cablepath.retrace()


@receiver(post_save, sender=FrontPort)
def extend_rearport_cable_paths(instance, created, raw, **kwargs):
    """
    When a new FrontPort is created, add it to any CablePaths which end at its corresponding RearPort.
    """
    if created and not raw:
        rearport = instance.rear_port
        for cablepath in CablePath.objects.filter(_nodes__contains=rearport):
            cablepath.retrace()
