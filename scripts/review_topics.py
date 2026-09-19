"""Detailed audit coverage, separate from the immutable ten-check score."""
TOPICS = {
    'citability': {
        'answers': 'Direct answers and extractable passages',
        'structure': 'Headings, lists and answer structure',
        'specificity': 'Specific facts and attribution',
        'page_comparison': 'Stronger and weaker pages with examples',
        'content_guide': 'Optional AI content guide (llms.txt)',
    },
    'authority': {
        'identity': 'Business identity across sources',
        'profiles': 'Relevant professional profiles and directories',
        'publications': 'Independent publications and bylines',
        'reviews': 'Client reviews and result verification',
        'community': 'Relevant communities, video and events',
        'entity_records': 'Existing public entity records',
    },
    'content': {
        'customer_questions': 'Customer questions and offer completeness',
        'experience': 'First-hand experience and proof',
        'expertise': 'Expertise and accountable authorship',
        'trust': 'Sources, dates and claim accuracy',
        'readability': 'Content depth, headings and readability',
        'topical_coverage': 'Topic coverage and internal connections',
        'freshness': 'Freshness and outdated information',
    },
    'technical': {
        'responses': 'Page access, errors and redirects',
        'robots': 'Search crawler access instructions',
        'sitemaps': 'Sitemaps and intended public pages',
        'metadata': 'Titles, descriptions and canonical URLs',
        'rendering': 'Rendered content and JavaScript dependency',
        'mobile': 'Mobile layout and basic accessibility',
        'performance': 'Measured speed and Core Web Vitals',
        'security': 'HTTPS and relevant security headers',
        'urls_links': 'URL structure and internal links',
    },
    'schema': {
        'inventory': 'Structured information inventory',
        'syntax': 'Parsing and malformed structured information',
        'semantics': 'Property types and entity relationships',
        'parity': 'Agreement with visible page content',
        'entity_links': 'Business and author identity links',
        'eligibility': 'Applicable search feature requirements',
        'recommendations': 'Page-specific corrections and examples',
    },
}

CATEGORY_NAMES = {
    'citability': 'Content clarity and citability',
    'authority': 'External reputation and supporting sources',
    'content': 'Content quality and customer usefulness',
    'technical': 'Website access and technical foundations',
    'schema': 'Structured information for search engines',
}

CRITERION_NAMES = {
    'direct_answers': 'Answers the main customer question',
    'specific_information': 'Provides concrete, attributable details',
    'identity_consistency': 'Consistent business identity',
    'independent_support': 'Independent support for material claims',
    'customer_completeness': 'Covers questions, conditions and next steps',
    'accountability': 'Identifies responsibility and supports claims',
    'content_access': 'Useful content accessible in captured responses',
    'search_directives': 'Public pages not blocked by observed instructions',
    'markup_syntax': 'Structured information parses successfully',
    'markup_parity': 'Structured information matches visible content',
}
