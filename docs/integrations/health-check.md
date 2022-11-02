# Health Check

NetBox provides health check monitors that can be queried to make sure that the service is running in good condition.  

NetBox exposes metrics at the `/healthcheck` HTTP endpoint, e.g. `https://netbox.local/healthcheck`. It allows monitor conditions via HTTP(S), with responses available in HTML and JSON formats.


## Setting up Monitoring

NetBox makes use of the [django-health-check](https://github.com/revsys/django-health-check) library, more information on setting up monitors can be found at [Setting up Monitoring](https://django-health-check.readthedocs.io/en/latest/readme.html#setting-up-monitoring):
