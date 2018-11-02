# (C) Datadog, Inc. 2018
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
import requests
import simplejson as json
from urlparse import urljoin

from datadog_checks.checks import AgentCheck


SEVERITIES = {
    'total': 'all',
    'high': 'high',
    'medium': 'medium',
    'ok': 'ok',
    'low': 'low'
}


class AquaCheck(AgentCheck):
    """
    Collect metrics from Aqua.
    """
    def check(self, instance):
        self.validate_instance(instance)
        try:
            token = self.get_aqua_token(instance)
        except Exception as ex:
            self.log.error("Failed to get Aqua token, skipping check. Error: %s" % ex)
            return
        self._report_base_metrics(instance, token)
        self._report_connected_enforcers(instance, token)
        status_metrics = [
            # (
            #     metric_name,
            #     route,
            #     statuses
            # )
            (
                'aqua.audit.access'
                '/api/v1/audit/access_totals?alert=-1&limit=100&time=hour&type=all',
                {
                    'total': 'all',
                    'success': 'success',
                    'blocked': 'blocked',
                    'detect': 'detect',
                    'alert': 'alert'
                }
            ),
            (
                'aqua.scan_queue',
                '/api/v1/scanqueue/summary',
                {
                    'total': 'all',
                    'failed': 'failed',
                    'in_progress': 'in_progress',
                    'finished': 'finished',
                    'pending': 'pending'
                }
            )
        ]

        for metric_name, route, statuses in status_metrics:
            self._report_status_metrics(instance, token, metric_name, route, statuses)

    def validate_instance(self, instance):
        """
        Validate that all required parameters are set in the instance.
        """
        if any(map(lambda x: x not in instance, ['api_user', 'password', 'url'])):
            raise Exception("Aqua instance missing one of api_user, password, or url")

    def get_aqua_token(self, instance):
        """
        Retrieve the Aqua token for next queries.
        """
        headers = {'Content-Type': 'application/json','charset':'UTF-8'}
        data={ "id": instance['api_user'], "password": instance['password'] }
        res = requests.post(instance['url'] + '/api/v1/login', data=json.dumps(data),headers=headers, timeout=self.default_integration_http_timeout)
        res.raise_for_status()
        return json.loads(res.text)['token']

    def _perform_query(self, instance, route, token):
        """
        Form queries and interact with the Aqua API.
        """
        headers = {'Content-Type': 'application/json','charset':'UTF-8','Authorization': 'Bearer '+ token}
        res = requests.get(urljoin(instance['url'], route), headers=headers, timeout=60)
        res.raise_for_status()
        return json.loads(res.text)

    def _report_base_metrics(self, instance, token):
        """
        Report metrics about images, vulnerabilities, running containers, and enforcer hosts
        """
        try:
            metrics = self._perform_query(instance, '/api/v1/dashboard', token)
        except Exception as ex:
            self.log.error("Failed to get base metrics. Some metrics will be missing. Error: %s" % ex)
            return

        # images
        metric_name = 'aqua.images'
        image_metrics = metrics['registry_counts']['images']
        for sev, sev_tag in SEVERITIES.iteritems():
            self.gauge(metric_name, image_metrics[sev], tags=instance.get('tags', []) + ['severity:%s' % sev_tag])

        # vulnerabilities
        metric_name = 'aqua.vulnerabilities'
        vuln_metrics = metrics['registry_counts']['vulnerabilities']
        for sev, sev_tag in SEVERITIES.iteritems():
            self.gauge(metric_name, vuln_metrics[sev], tags=instance.get('tags', []) + ['severity:%s' % sev_tag])

        # running containers
        metric_name = 'aqua.running_containers'
        container_metrics = metrics['running_containers']
        # FIXME: haissam is the tagging and substraction logic legit here?
        self.gauge(metric_name, container_metrics['total'], tags=instance.get('tags', []) + ['status:all'])
        self.gauge(metric_name, container_metrics['unregistered'], tags=instance.get('tags', []) + ['status:unregistered'])
        self.gauge(metric_name, container_metrics['total'] - container_metrics['unregistered'], tags=instance.get('tags', []) + ['status:registered'])

        # disconnected enforcers
        # FIXME: haissam should we move this to the dedicated enforcer method?
        metric_name = 'aqua.enforcers'
        enforcer_metrics = metrics['hosts']
        self.gauge('aqua.enforcers', enforcer_metrics['disconnected_count'], tags=instance.get('tags', []) + ['status:disconnected'])

    def _report_status_metrics(self, instance, token, metric_name, route, statuses):
        try:
            metrics = self._perform_query(instance, route, token)
        except Exception as ex:
            self.log.error("Failed to get %s metrics. Error: %s" % (metric_name, ex))
            return
        for status, status_tag in status.iteritems():
            self.gauge(metric_name, metrics[status], tags=instance.get('tags', []) + ['status:%s' % status_tag])

    def _report_connected_enforcers(self, instance, token):
        """
        Report metrics about enforcers
        """
        # FIXME: haissam is there more to collect here?
        try:
            metrics = self._perform_query(instance, '/api/v1/hosts', token)
        except Exception as ex:
            self.log.error("Failed to get enforcer metrics. Error: %s" % ex)
            return

        # FIXME: haissam is it all or connected here?
        self.gauge('aqua.enforcers', metrics['count'], tags=instance.get('tags', []) + ['status:all'])