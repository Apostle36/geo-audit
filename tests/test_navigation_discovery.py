import unittest

from collect import Client, discover, navigation_candidates
from evidence import validate_registry
from test_collect_contract import serve, serve_site


class NavigationDiscovery(unittest.TestCase):
    def test_empty_sitemap_fallback_only_fetches_the_starting_page(self):
        routes={'/':(200,{'Content-Type':'text/html'},b'''<title>Home</title>
            <a href="/services#details">Services</a><a href="/about">About</a>
            <a href="https://elsewhere.example/">Outside</a><a href="/guide.pdf">File</a>
            <a href="/services">Duplicate</a><a href="mailto:a@example.com">Email</a>''')}
        with serve(routes) as (base,server):
            summary,evidence=discover(Client(delay=0,allow_private=True,proxies={}),base+'/')
            paths=[path for path,_ in server.requests]
        self.assertEqual([item['loc'] for item in summary['candidates']],[base+'/',base+'/services',base+'/about'])
        self.assertTrue(summary['navigation']['used'])
        self.assertEqual(summary['navigation']['status'],'success')
        self.assertNotIn('/services',paths)
        self.assertNotIn('/about',paths)
        self.assertEqual(paths.count('/'),1)
        validate_registry(evidence)

    def test_successful_sitemap_does_not_trigger_navigation(self):
        with serve_site() as (base,server):
            summary,_=discover(Client(delay=0,allow_private=True,proxies={}),base+'/')
        self.assertFalse(summary['navigation']['used'])
        self.assertNotIn('/',[path for path,_ in server.requests])

    def test_robots_denial_prevents_seed_fetch_and_candidates(self):
        routes={'/robots.txt':(200,{'Content-Type':'text/plain'},b'User-agent: *\nDisallow: /\n')}
        with serve(routes) as (base,server):
            summary,evidence=discover(Client(delay=0,allow_private=True,proxies={}),base+'/')
        self.assertEqual(summary['candidate_count'],0)
        self.assertEqual(summary['navigation']['status'],'unavailable')
        self.assertNotIn('/',[path for path,_ in server.requests])
        self.assertEqual(evidence[-1]['status'],'unavailable')

    def test_fallback_is_bounded_and_can_be_disabled(self):
        html=b'<title>Home</title><a href="/a">A</a><a href="/b">B</a><a href="/c">C</a>'
        with serve({'/':(200,{'Content-Type':'text/html'},html)}) as (base,server):
            summary,_=discover(Client(delay=0,allow_private=True,proxies={}),base+'/',max_urls=2)
            self.assertEqual(summary['candidate_count'],2)
            self.assertTrue(summary['navigation']['truncated'])
            count=len(server.requests)
            summary,_=discover(Client(delay=0,allow_private=True,proxies={}),base+'/',navigation_fallback=False)
            self.assertFalse(summary['navigation']['used'])
            self.assertNotIn('/',[path for path,_ in server.requests[count:]])

    def test_base_tags_credentials_and_non_html_links_do_not_escape_scope(self):
        candidates,_=navigation_candidates('<base href="https://elsewhere.example/"><a href="/x">X</a>'
            '<a href="https://user:pass@example.com/">Credentials</a>',
            'https://example.com/','https://example.com/',100)
        self.assertEqual([item['loc'] for item in candidates],['https://example.com/'])


if __name__=='__main__':
    unittest.main()
