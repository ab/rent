#!/usr/bin/env python

"""
usage: rent.py YAML_FILE [dry|real]

Send a rent reminder email based on data from YAML_FILE.

If dry is passed, no email will actually be sent.
"""

import smtplib
import sys
import yaml
from datetime import date, timedelta

def first_next_month(start):
    if start.month == 12:
        return date(start.year + 1, 1, 1)
    else:
        return date(start.year, start.month + 1, 1)

class NoUtilityInfo(KeyError):
    pass

def usage():
    sys.stderr.write(__doc__.lstrip())

class RentComponent(object):
    def __init__(self, name, total, divided_among):
        self.name = name
        self.total = total
        self.divided_among = divided_among

        if divided_among > 1:
            self.share = float(total) / divided_among
        elif divided_among == 1:
            self.share = total
        else:
            raise ValueError('Unexpected divided_among: %r' % divided_among)

    def __str__(self):
        if self.divided_among == 1:
            return '{}: {:.2f}'.format(self.name, self.total)
        else:
            return '{}: {:.2f} = {:.2f} / {}'.format(
                self.name, self.share, self.total, self.divided_among)

class RentReminder(object):
    def __init__(self, config_file, rent_date=None, smtp_server='localhost',
                 dry_run=True):
        self.config = self.load_config(config_file)
        if rent_date is None:
            self.today = date.today()
        else:
            self.today = rent_date
        self.due_date = first_next_month(self.today)
        self.smtp_server = smtp_server
        self.dry_run = dry_run

    def load_config(self, filename):
        return yaml.safe_load(open(filename, 'r'))

    def rent_for(self, name):
        """Return the current rent for a given person"""
        return self.due_date_rents()[name]

    def utility_info(self):
        utilities = self.config['utilities']
        try:
            return utilities[self.today.year][self.today.month]
        except KeyError:
            month = self.today.strftime('%Y-%m')
            raise NoUtilityInfo('No utility info for ' + month)

    def utility_info_share(self):
        return dict((k, float(v) / self.num_payers()) for k, v in
                    self.utility_info().iteritems())

    def num_payers(self):
        return len(self.config['people']) + 1

    def total_for(self, name):
        return sum(p.share for p in self.parts_for(name))

    def all_rents(self):
        return self.config['rent']

    def due_date_rents(self):
        """Return a dict mapping name to rent for the due date."""
        if not hasattr(self, '_due_date_rents'):
            self._due_date_rents = self.rents_as_of(self.due_date)

        return self._due_date_rents

    def rents_as_of(self, rent_date):
        """
        Return a dict mapping name to rent for the given date.
        """
        if rent_date is None:
            rent_date = date.today()

        for rent_hash in reversed(self.all_rents()):
            if rent_date >= rent_hash['since']:
                print 'Using rent as of', rent_hash['since']
                return rent_hash['splits']

        raise KeyError('Cannot find rent for %r' % rent_date)

    def due_month_name(self):
        return self.due_date.strftime('%B')

    def parts_for(self, name):
        """Return a list of RentComponent objects for person `name`."""
        parts = []
        parts.append(RentComponent('Rent', self.rent_for(name), 1))

        for k, v in sorted(self.utility_info().iteritems()):
            parts.append(RentComponent(k, float(v), self.num_payers()))

        return parts

    def payment_links_for(self, name, total):
        links = []

        person_config = self.config['people'][name]

        if person_config.get('paypal_me'):
            links.append('https://www.paypal.me/{}/{:.2f}'.format(
                self.config['payment_links']['paypal'], total))

        if person_config.get('square_me'):
            links.append('https://cash.me/{}/{:.2f}'.format(
                self.config['payment_links']['square'], total))

        return links

    def email_for(self, name):
        person_config = self.config['people'][name]
        from_address = self.config['email']['from']
        to_address = person_config['email']
        recipients = [to_address]
        headers = [
            ('From', from_address),
            ('To', to_address),
        ]
        if person_config['cc']:
            headers.append(('Cc', person_config['cc']))
            recipients.append(person_config['cc'])

        recipients.append(self.config['email']['bcc'])

        parts = self.parts_for(name)
        total = round(sum(p.share for p in parts), 2)
        assert total == round(self.total_for(name), 2) # useless double check

        subject = "{} rent is ${:.2f}".format(self.due_month_name(), total)

        headers.append(('Subject', subject))

        header_block = '\n'.join(name + ': ' + val for name, val in headers)

        parts_block = '\n'.join(str(p) for p in parts)

        parts_block += '\n' + '=' * 14
        parts_block += '\nTotal: {:.2f}'.format(total)

        links = self.payment_links_for(name, total)

        if links:
            parts_block += '\n\n' + '\n'.join(links)

        return {
            'from': from_address,
            'recipients': recipients,
            'message': header_block + '\n\n' + parts_block + '\n',
        }

    def send_email_for(self, name):
        print '==='
        print 'Generating email for {}'.format(name)
        data = self.email_for(name)

        for i in ['from', 'recipients', 'message']:
            print i + ':', repr(data[i])

        self.send_email(data['from'], data['recipients'], data['message'])

    def send_email(self, from_address, recipients, data):
        if self.dry_run:
            print 'Not sending email due to dry run'
            for line in data.split('\n'):
                print '| ' + line
            return

        s = smtplib.SMTP(self.smtp_server)
        s.set_debuglevel(1)
        s.sendmail(from_address, recipients, data)
        s.quit()

        print 'Sent email'


    def send_all_email(self):
        for name in self.config['people'].keys():
            self.send_email_for(name)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        usage()
        sys.exit(1)

    if sys.argv[2] == 'dry':
        dry_run = True
    elif sys.argv[2] == 'real':
        dry_run = False
    else:
        usage()
        sys.exit(1)

    r = RentReminder(sys.argv[1], dry_run=dry_run)
    r.send_all_email()

