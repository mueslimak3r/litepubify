# -*- coding: utf-8 -*-
"""Downloads stories from the website literotica.com and compiles them to an .epub file.

Note: The author of this scipt has no connection to literotica.com, this
is just a hobby project.

To fetch an entire series, just provide the URL of one of the stories.
(The program will download the list of story submissions on the
memberpage of the author and get the links to other parts of the series.)

written for python 2.6, 2.7, >=3

License: CC0 (public domain)
"""

from __future__ import unicode_literals

import argparse
import hashlib
import io
import mimetypes
import os
import re
import sys
import uuid
import xml.sax.saxutils as saxutils
import zipfile
import bs4
import urllib
import ssl
from time import sleep

# python 2 / 3 compatibility code
try:
    import urllib.request as compat_urllib_request
    import urllib.parse as compat_urllib_parse
except ImportError: # python 2
    import urllib2 as compat_urllib_request
    import urlparse as compat_urllib_parse
try:
    import html.parser as compat_html_parser
except ImportError: # python 2
    import HTMLParser as compat_html_parser
try:
    from html import escape as compat_escape
except ImportError: # python 2
    from cgi import escape as compat_escape
if sys.version < '3':
    text_type = unicode
    binary_type = str
else:
    text_type = str
    binary_type = bytes
def get_content_type(response):
    """Get the content-type from a download response header.

    Args:
      response (Python 2: urllib.addinfourl; Python 3: http.client.HTTPResponse): the http response object

    Returns:
      text: the content type from the headers

    """
    try:
        return response.info().get_content_type()
    except AttributeError: # python 2
        t = response.info().type
        return t.decode('UTF-8')


VERSION = '0.1'     # the program version

args = None         # command line arguments
url_mem_cache = {}  # cache for downloaded websites

all_oneshots = None # all the oneshot stories found, global for debugging
all_series = None   # all the series found, global for debugging

def main():
    global all_oneshots
    global all_series

    parse_commandline_arguments()

    story_html, _ = fetch_url(args.url[0])

    (title, author, memberpage_url) = parse_story_header(story_html)
    debug("title: '{}', author: '{}', memberpage: '{}'".format(title, author, memberpage_url))

    memberpage, _ = fetch_url(memberpage_url)
    (all_oneshots, all_series) = parse_author_works_page(memberpage)

    if args.debug:
        debug('ALL STORIES BY AUTHOR {}:'.format(author))
        for st in all_oneshots:
            debug('{}'.format(st))
        debug('ALL SERIES:'.format(author))
        for series in all_series:
            debug('{}'.format(series.title))
            for st in series.stories:
                debug('    {}'.format(st))

    found_oneshots_and_series = []
    for url in args.url:
        story_html, _ = fetch_url(url)
        page_id = extract_id(url)
        print("target id [%s]" % str(page_id))
        found_story = None
        found_series = None
        print("searching oneshots for target id [%s]" % str(page_id))
        for st in all_oneshots:
            print(extract_id(st.url))
            if extract_id(st.url) == page_id:
                found_story = st
                found_oneshots_and_series.append(found_story)
                break

        if not found_story:
            print("searching series for target id [%s]" % str(page_id))
            for series in all_series:
                print("searching series for target id [%s]" % str(page_id))
                if extract_id(series.url) == page_id:
                    found_series = series
                    found_story = series.stories[0]
                    if args.single:
                        found_oneshots_and_series.append(found_story)
                    else:
                        found_oneshots_and_series.append(series)
                    break
                for story in series.stories:
                    if extract_id(story.url) == page_id:
                        found_story = story
                        found_series = series
                        if args.single:
                            found_oneshots_and_series.append(story)
                        else:
                            found_oneshots_and_series.append(series)
                        break
                if found_series: break

            if not found_series: error("Couldn't find story on members page")

            if args.debug:
                debug(found_series.title)
                for story in found_series.stories:
                    debug('  {}'.format(story))

    if args.author: author = args.author
    make_epub_from_stories_and_series(found_oneshots_and_series, author)

def parse_commandline_arguments():
    """Parse the command line arguments.
    """
    global args
    parser = argparse.ArgumentParser()
    parser.add_argument('url', nargs='+', help='URL of the story, or one of the stories in the series')
    parser.add_argument('-a', '--author', help='override the author in the epub metadata')
    parser.add_argument('-t', '--title', help='override the title in the epub metadata and default file name')
    parser.add_argument('-o', '--output', metavar='FILENAME', help='set output file name (optional, otherwise story title is used)')
    parser.add_argument('-s', '--single', action='store_true', help='do not attempt to download the entire series (if it is a series) but just this one story')
    parser.add_argument('-n', '--newer', action='store_true', help='only download the series parts including and after the specified ID (if it is a series)')
    parser.add_argument('--noteaser', action='store_true', help='do not include the one line teaser in the table of contents')
    parser.add_argument('--noimages', action='store_true', help='do not include any images (in case of illustrated stories)')
    parser.add_argument('-v', '--verbose', action='store_true', help='output more information')
    parser.add_argument('-d', '--debug', action='store_true', help='output debug information')
    parser.add_argument('--silent', action='store_true', help='suppress informational output')
    parser.add_argument('--disk-cache-path', metavar='PATH', help='Path for the disk cache (optional, usually not required). If this option is specified, downloaded websites are cached in a file and loaded from disk in subsequent runs (when this option is used again with the same path). This is mainly useful for testing, to avoid repeated downloads. Without this option, litepubify keeps everything in memory and only writes the final epub file to disk.')
    args = parser.parse_args()


def parse_story_header(html):
    soup = bs4.BeautifulSoup(html, 'html.parser')
    title_tag = soup.find('h1', class_='headline')
    if title_tag:
        title = title_tag.text.strip()
    else:
        error("Cannot find title in html.")
    #element = soup.find('a', class_='icon-account-plus')
    element = soup.find('div', {'title' : 'Stories'})
    #print(element)
    if element:
        url = str((element.find_all("a", recursive=False))[0]['href'])
        # url = "/".join(url.split('/')[:-1])
        author = url.split('/')[-2]
    else:
        error("Cannot find author link in html.")
        error("Cannot find author's member page link in html.")

    if title:
        title = saxutils.escape(title)
        print(title)
    if author:
        author = saxutils.escape(author)
    return title, author, url
    

def make_epub_from_stories_and_series(stories_and_series, author):
    """Make epub file from story or series.

    Args:
        s (Story or Series): the story or series to make an epub from

    """
    book = EpubBook()
    book.title = saxutils.escape(stories_and_series[0].title)
    if args.title:
        info(args.title)
        book.title = saxutils.escape(args.title)
        info(args.title)
    book.creator = author

    cover_txt = COVER_TEMPLATE.format(
        title=book.title,
        author=author)
    cover_html = TXT_HTML_TEMPLATE.format(title='cover', content=cover_txt)
    book.add_cover(cover_html)

    s_count = 1

    total_count = 0
    for s_obj in stories_and_series:
        if isinstance(s_obj, Story):
            total_count += 1
        else:
            total_count += len(s_obj.stories)
    print("total stories and series [%s]" % total_count)

    arg_url_id = extract_id(args.url[0])
    newer_mode = False
    if args.newer:
        print("-n flag enabled - will only save series parts including and proceeding the specified story")
        newer_mode = True

    for s in stories_and_series:
        if isinstance(s, Story):
            add_story_to_ebook(s, 'content{0:02d}.html'.format(s_count), book)
        else:
            chap_count = 1
            should_add = True
            if args.newer:
                should_add = False
            for st in s.stories:
                if newer_mode:
                    if arg_url_id == extract_id(s.url):
                        newer_mode = False
                        print("newer mode disabled - url provided does not match a part in a series")
                    elif arg_url_id == extract_id(st.url):
                        should_add = True
                    elif not should_add and arg_url_id != extract_id(st.url):
                        print("skipping series part %s - looking for part %s" % (extract_id(st.url), arg_url_id))
                        continue
                add_story_to_ebook(
                    st,
                    'part{0:02d}x{1:02d}.html'.format(s_count, chap_count),
                    book)
                chap_count += 1
                #info(chap_count)
        s_count += 1
        

    path = re.sub(r'[^\w_. -]', r'_', book.title, flags=re.UNICODE)
    arch_filename = path + '.epub'
    #book.make_epub_unpacked(path)      # for testing
    if args.output:
        arch_filename = args.output
    book.make_epub(arch_filename)
    info("finished, written to '{}'".format(arch_filename))

def add_story_to_ebook(st, filename, book):
    """Add a story to an ebook.

    Args:
        st (Story): the story
        filename (text): filename for the section in the ebook
        book (EpubBook): the book
    """
    txt = get_story_text(st)
    txt = make_tags_lowercase(txt)

    # include image files and make fix image URLs
    def sub_img(m):
        if args.noimages:
            return ''
        pattern = re.compile(r' src="(.*?)"')
        rel_url_match = re.search(pattern, m.group(0))
        rel_url = rel_url_match.group(1)
        url = compat_urllib_parse.urljoin(st.url, rel_url)
        img_data, mime_type = fetch_url(url, binary=True)
        parsed_url = compat_urllib_parse.urlparse(url)
        path = parsed_url.path
        filename = os.path.basename(path)
        final_url = book.add_image(filename, img_data, mime_type)
        return re.sub(pattern, ' src="{}"'.format(final_url), m.group(0))

    txt = re.sub(r'<img.*?>', sub_img, txt)

    txt = make_tags_xml_compliant(txt)

    cleaner = XHTMLCleaner()
    cleaner.feed(txt)
    txt = cleaner.get_output()
    txt = TITLE_TEMPLATE.format(title=st.title, author=st.author) + re.sub("&(?!amp;)", "&amp;", txt)
    html = TXT_HTML_TEMPLATE.format(title=saxutils.escape(book.title), content=txt)
    book.add_html(st.title, st.teaser, html, filename)

def make_tags_lowercase(html):
    """Convert tags like <I>...</I> to lowercase version <i>...</i>.

    This has to be done for xhtml 1.1 compliance.
    The method with regex is sort of hackish, but should work for most cases.

    Args:
      html (text): the html text

    Returns:
      text: the fixed html text
    """
    def tag_lower(tag_match):
        t = tag_match.group(0)
        t = re.sub(r'<\s*/?\s*(\w+)[\s/>]', lambda s: s.group(0).lower(), t)
        return re.sub(r'\w+="', lambda s: s.group(0).lower(), t)
    return re.sub(r'<.*?>', tag_lower, html)

def make_tags_xml_compliant(html):
    """Make sure, the tags are proper XML.

    Converts <img ... > to <img ... />. (Same for <br>)

    We do not handle the case where there is an opening
    and an closing tag, for example <br></br> as it is
    not very common.

    Args:
        html (text): the html text

    Returns:
      text: the fixed html text
    """
    tags = ['img', 'br']
    for tag in tags:
        def check_and_fix(m):
            s = m.group(1)
            if not s.lstrip().startswith(tag):
                return m.group(0)
            check_match = re.search(r'/\s*$', s)
            if check_match:
                return m.group(0)
            else:
                return '<' + s + '/>'
        html = re.sub(r'<(.*?)>', check_and_fix, html)
    return html

class XHTMLCleaner(compat_html_parser.HTMLParser):
    """Fixes certain problems with broken tags in HTML.

    It detects closing tags that have not been opened before and strips those.

    E.g. the string
        "this is </i>so</i> broken <br/>"
    becomes
        "this is so broken <br/>".

    """
    def __init__(self):
        compat_html_parser.HTMLParser.__init__(self)
        self.open_tags = {}
        self.accum = ''

    def handle_starttag(self, tag, attr):
        if not tag in self.open_tags:
            self.open_tags[tag] = 0
        self.open_tags[tag] += 1
        self.out(self.get_starttag_text())
    def handle_endtag(self, tag):
        if not tag in self.open_tags:
            self.open_tags[tag] = 0
        if self.open_tags[tag] <= 0: # this is a problem - omit tag
            return
        self.open_tags[tag] -= 1
        self.out("</"+tag+">")
    def handle_startendtag(self, tag, attr):
        self.out(self.get_starttag_text())
    def handle_data(self, data):
        self.out(data)
    def handle_entityref(self, name):
        self.out('&'+name+';')
    def handle_charref(self, name):
        self.out('&#'+name+';')
    def handle_comment(self, data):
        self.out('<!--'+data+'-->')

    def out(self, data):
        self.accum += data

    def get_output(self):
        return self.accum

def validate_classes(element, rules):
    classes = element["class"]
    required_classes = rules[0]
    excluded_classes = rules[1]
    if not required_classes or not classes:
        return False

    rc_idx = 0
    found_classes = []
    for c in classes:
        for ec in excluded_classes:
            if c.startswith(ec):
                return False
        if rc_idx < len(required_classes):
            for rc in required_classes[rc_idx:]:
                if c.startswith(rc):
                    found_classes.append(c)
                    rc_idx += 1
    return len(list(set(found_classes))) == len(required_classes)

def parse_series_page(page_url, author):
    html, _ = fetch_url(page_url)
    soup = bs4.BeautifulSoup(html, 'html.parser')
    chapters_container = soup.select("ul[class=series__works]")[0]
    chapter_elements = chapters_container.find_all('li', recursive=False)
    stories = []
    for chapter_elem in chapter_elements:
        story = Story()
        title_elem = chapter_elem.find_all('a', recursive=False)[0]
        story.url = title_elem['href']
        story.title = saxutils.escape(title_elem.text.strip())
        story.author = author

        subtitle_elem = chapter_elem.find_all('p', recursive=False)[0]
        story.category = subtitle_elem.find_all('a', recursive=False)[0].text.strip()
        teaser = subtitle_elem.text.strip()
        story.teaser = saxutils.escape(teaser.replace(story.category, '').strip())

        story.rating = 0.0
        story.hot = False
        story.date = ""
        stories.append(story)
    return stories

def parse_author_works_page(html):
    soup = bs4.BeautifulSoup(html, 'html.parser')
    author_element = soup.find('title')
    if not author_element:
        error("Cannot determine author on member page.")
    if "Stories by " in author_element.text.strip():
        author = saxutils.escape(author_element.text.strip().replace("Stories by ", "").strip())
    else:
        error("Cannot determine author on member page.")
    subm_table_match = soup.select("div[class^=_works_wrapper]")
    if not subm_table_match:
        error("Cannot find submission table.")
    subm_table_match = subm_table_match[0]
    trs = subm_table_match.find_all('div', recursive=False)
    #trs = subm_table_match.select("div[class^=_works_item]", recursive=False)
    print("trs %s " % len(trs))

    #trs = re.findall(r'(<tr.*?</tr>)', subm_table_match.group(1), re.DOTALL)
    all_series = []
    all_oneshots = []
    series = None
    story = None
    ONESHOT_CLASS = (['_works_item'], [])
    SERIES_CLASS = (['_works_item__series_expanded_header_card'], [])
    for tr in trs:
        #print(tr["class"])
        if validate_classes(tr, SERIES_CLASS):
            print("Series: " + tr.select("a[class^=_item_title]")[0].text)
            series = Series()
            series.title = saxutils.escape(tr.select("a[class^=_item_title]")[0].text.strip())
            series.author = author
            series_url = tr.select("a[class^=_item_title]")[0]['href']
            series.url = series_url
            print(series_url)
            series.stories = parse_series_page(series_url, author)
            all_series.append(series)
        elif validate_classes(tr, ONESHOT_CLASS):
            print("Story: " + tr.select("a[class^=_item_title]")[0].text)
            story_stats_elem = tr.select("div[class^=_stats]")[0]
            story = Story()
            story.title = saxutils.escape(tr.select("a[class^=_item_title]")[0].text.strip())
            story.author = author
            story.url = tr.select("a[class^=_item_title]")[0]['href']
            if not story.url.startswith('https://www.literotica.com'):
                story.url = "https://www.literotica.com" + story.url
            rating_elem = story_stats_elem.find('span', {'title' : 'Rating'})
            if rating_elem:
                story.rating = rating_elem.find_all('span', recursive=False)[0].text.strip()
            else:
                story.rating = "0.0"
            story.hot = True if story_stats_elem.find('span', {'title' : 'Hot'}) else False
            story.category = tr.select("a[class^=_item_category]")[0].text.strip()
            story.date = tr.select("span[class^=_date_approve]")[0].text.strip()
            story.teaser = "" if not tr.select("p[class^=_item_description]") else saxutils.escape(tr.select("p[class^=_item_description]")[0].text.strip())
            all_oneshots.append(story)
    print("total oneshots [%d], total series [%d]" % (len(all_oneshots), len(all_series)))
    return (all_oneshots, all_series)


def extract_id(url):
    """Extract the story id from a URL.

    Args:
      url: the URL

    Returns:
      the story id (the last part in the url path component)

    """
    o = compat_urllib_parse.urlparse(url)
    p = o.path
    p = re.sub('/$', '', p)
    idx = p.rfind('/')
    if idx == -1: error("unexpected url: {}".format(url))
    url_id = p[idx+1:]
    print("url_id [%s]" % url_id)
    return url_id

def get_story_text(st):
    #print('getting text')
    html, _ = fetch_url(st.url) # assuming url leads to first page and has no query part
    soup = bs4.BeautifulSoup(html, 'html.parser')
    paginator_parent_element = soup.find('span', {'title' : 'Previous Page'})
    if paginator_parent_element:
        paginator_parent_element = paginator_parent_element.parent
        paginator_elements = paginator_parent_element.find_all('a', recursive=False)
    else:
        paginator_elements = [ 1 ]
    #sel_match = re.search(r'<div class="b-pager-pages">(.*?)</div>', html)
    
    #[0].select("div[class^=_item_title]")[0]['href']

    #vals = re.findall('<option value=".*?">(\d+)</option>', sel_match.group(1))
    complete_text = ""

    end = 1
    if paginator_parent_element:
        for pe in paginator_elements:
            if pe.text.strip() == '' or not pe.text.strip().isnumeric():
                continue
            if int(pe.text.strip()) > end:
                end = int(pe.text.strip())
    
    for idx in range(1, end+1):
        #print("page %s" % idx)

        url_suffix = "" if idx == 1 else "?page={current_page}".format(current_page=idx)
        url = st.url + url_suffix

        story_page_html, _ = fetch_url(url)
        story_page_soup = bs4.BeautifulSoup(story_page_html, 'html.parser')
        #print(story_page_soup)
        #text_parent = story_page_soup.find('div', {'panel' : 'article'})
        text_parent = story_page_soup.select('.panel.article')[0]
        if not text_parent:
            error("Couldn't find text body.")
        
        #print(text_parent)
        
        text_elements = text_parent.find_all('p', recursive=True)
        lines = ""
        for elem in text_elements:
            #print(elem)
            #print(elem.text)
            if elem.text is None or elem.text == "":
                continue
            #print(elem.text)
            lines += "\n{}".format(str(elem)) if lines != "" else str(elem)
        if idx > 1:
            complete_text += '\n\n' + lines
        else:
            complete_text = lines
    if complete_text == "":
        warning('Unable to extract text for {}.'.format(st.url))
    return "<p>%s</p>" % complete_text


class FrozenClass(object):
    """Auxiliary base class to prevent access to attributes that haven't been set in __init__
    """
    __isfrozen = False
    def __setattr__(self, key, value):
        if self.__isfrozen and not hasattr(self, key):
            raise TypeError("key not set: %s; %r of type %s is a frozen class" % (key, self, type(self)) )
        object.__setattr__(self, key, value)

    def _freeze(self):
        self.__isfrozen = True


class Story(FrozenClass):
    """A single story.

    Attributes:
      title (text): the title of the story
      teaser (text): a one line description
      author (text): the author
      url: download url
      rating: the rating
      hot (bool): if the story is rated as hot or not
      category (text): a category
      date: date of publication

    """
    def __init__(self):
        self.title = None
        self.teaser = None
        self.author = None
        self.url = None
        self.rating = None
        self.hot = None
        self.category = None
        self.date = None
        self._freeze()

    def __repr__(self):
        return '<"{}" - "{}" ({}) {}{} - {}, {}>'.format(self.title, self.teaser, self.rating, 'H ' if self.hot else '', self.url, self.category, self.date)
        return str(vars(self))

class Series(FrozenClass):
    """A series of multiple stories.

    Attributes:
      title (text): the title of the series
      author (text): the author of the series
      stories list(Story): the list of stories of the series

    """
    def __init__(self):
        self.title = None
        self.author = None
        self.url = None
        self.stories = []
        self._freeze()

    def __repr__(self):
        return str(self.stories)


def fetch_url(url, binary=False):
    """Download contents of a webpage.

    It does not check the encoding and simply
    assumes the document is UTF-8 encoded.

    Args:
      url: the URL of the webpage
      binary (bool): if the downloaded content is binary data, e.g. an image

    Returns:
      (data, mime_type):
        data: downloaded text, if binary is False, the downloaded binary data otherwise
        mime_type: The mime type of the data, e.g. image/png.
    """
    global url_mem_cache
    if url in url_mem_cache:
        return url_mem_cache[url]
    if args.disk_cache_path:
        path = os.path.join(args.disk_cache_path, url_to_filepath_hash(url))
        mime_path = os.path.join(args.disk_cache_path, url_to_filepath_hash(url) + 'MIME')
        if (os.path.isfile(path) and os.path.isfile(mime_path)):
            info("fetched from disk cache: '{}'".format(url))
            data = io.open(path, 'rb').read()
            if not binary:
                data = data.decode('UTF-8')
            mime_type = io.open(mime_path, 'rb').read()
            mime_type = mime_type.decode('UTF-8')
            url_mem_cache[url] = (data, mime_type)
            return data, mime_type
    debug("fetching '{}'...".format(url))
    req = compat_urllib_request.Request(url, headers={ 'User-Agent': get_user_agent() })
    # req = compat_urllib_request.Request(url, headers={ 'User-Agent': get_user_agent(), 'Cookie': 'enable_classic=1' })
    for i in range(5):
        try:
            response = compat_urllib_request.urlopen(req)
        except (urllib.error.URLError, ssl.SSLEOFError) as e:
            print("Error fetching '{}': {}".format(url, e))
        if response.getcode() == 200:
            break
        sleep(0.1)
        i += 1
    data = response.read()
    mime_type = get_content_type(response)
    if args.disk_cache_path:
        f = io.open(path, 'wb')
        f.write(data)
        f.close()
        f2 = io.open(mime_path, 'wb')
        f2.write(mime_type.encode('UTF-8'))
        f2.close()
    if not binary:
        data = data.decode('UTF-8')
    url_mem_cache[url] = (data, mime_type)
    return data, mime_type

def url_to_filepath_hash(url):
    salted = url+'la;l;vdoids'
    return hashlib.sha224(salted.encode('UTF-8')).hexdigest()

class EpubSection(FrozenClass):
    """One section / chapter of the ebook.

    Attributes:
      id (text): an id that is generated and used internally
      title (text): the title of the section / chapter
      teaser (text): a one line description which is included in the t.o.c.
      html (text): the html content
      filename (text): the filename, e.g. 'part1.html'

    """
    def __init__(self):
        self.id = ''
        self.title = ''
        self.teaser = ''
        self.html = ''
        self.filename = ''
        self._freeze()

class EpubImage(FrozenClass):
    """An image that will be included in the ebook.

    Attributes:
      id (text): an id that is generated and used internally
      filename (text): the filename, without path
      full_path (text): the full path for the image, as it will be saved in the ebook
      data (binary): the image file content
      mime_type (text): mime type for the image, e.g. image/png
    """
    def __init__(self):
        self.id = None
        self.filename = None
        self.full_path = None
        self.data = None
        self.mime_type = None
        self._freeze()

class EpubBook(FrozenClass):
    def __init__(self):
        self.root_dir = ''
        self.UUID = uuid.uuid1()
        self.sections = []
        self.images = []
        self.title = ''
        self.creator = ''
        self._cover = None
        self._freeze()

    def add_html(self, title, teaser, html, filename):
        """
        Add a new html file as a section / chapter of the epub.

        Args:
          title (text): the title of the section / chapter
          teaser (text): a one line description which is included in the t.o.c.
          html (text): the html content
          filename (text): the filename, e.g. 'part1.html'
        """
        section = EpubSection()
        section.id = 'html_%d' % (len(self.sections) + 1)
        section.filename = filename
        section.html = html
        print(title)
        section.title = title
        print(teaser)
        section.teaser = teaser
        self.sections.append(section)

    def add_image(self, filename, data, mime_type):
        """
        Add a new image file to be included in the epub.
        
        Args:
          filename (text): the filename of the image (without path)
          data (binary): the image file content
          mime_type (text): the mime_type of the image
        
        Returns:
          text: The final URL, for the <img src="..."/> tag in the XHTML.
        """
        image = EpubImage()
        num = '{:03d}'.format(len(self.images) + 1)
        image.id = 'img' + num
        image.filename = num + filename
        image.full_path = os.path.join('images', image.filename)
        image.data = data
        image.mime_type = mime_type
        self.images.append(image)
        return image.full_path

    def add_cover(self, html):
        self._cover = html

    def _write_mimetype(self, writer):
        writer.write('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)

    def _write_items(self, writer):
        if self._cover:
            writer.write(
                os.path.join('OEBPS', 'cover.html'),
                self._cover)
        for section in self.sections:
            writer.write(
                os.path.join('OEBPS', section.filename),
                section.html)
        for image in self.images:
            writer.write(
                os.path.join('OEBPS', image.full_path),
                image.data,
                binary=True)

    def _write_container_xml(self, writer):
        writer.write(os.path.join('META-INF', 'container.xml'), CONTAINER_TEMPLATE)

    def _write_content_opf(self, writer):
        metacover = ''
        manifest = ''
        spine = ''
        guide = ''
        if self._cover:
            metacover = META_COVER_TEMPLATE;
            manifest += MANIFEST_ITEM_TEMPLATE.format(
                id='cover',
                filename='cover.html',
                mediatype='application/xhtml+xml')
            spine += SPINE_ITEM_TEMPLATE.format(id='cover', add=' linear="no"')
            guide = GUIDE_TEMPLATE;
        for section in self.sections:
            manifest += MANIFEST_ITEM_TEMPLATE.format(
                id=section.id,
                filename=section.filename,
                mediatype='application/xhtml+xml')
            spine += SPINE_ITEM_TEMPLATE.format(id=section.id, add='')
        for image in self.images:
            manifest += MANIFEST_ITEM_TEMPLATE.format(
                id=image.id,
                filename=image.full_path,
                mediatype=image.mime_type)
        txt = CONTENT_TEMPLATE.format(
            title=saxutils.escape(self.title),
            creator=saxutils.escape(self.creator),
            uuid=self.UUID,
            metacover=metacover,
            manifest=manifest,
            spine=spine,
            guide=guide)
        writer.write(os.path.join('OEBPS', 'content.opf'), txt)

    def _write_toc_ncx(self, writer):
        nav_points = ''
        i = 1
        for section in self.sections:
            title = section.title
            if not args.noteaser and section.teaser:
                title += ' - ' + section.teaser
            nav_points += NAV_POINT_TEMPLATE.format(id=section.id, playorder=i, title=title, filename=section.filename)
            i += 1
        writer.write(os.path.join('OEBPS', 'toc.ncx'), NCX_TEMPLATE.format(uuid=self.UUID, title=self.title, nav=nav_points))

    def write_all(self, writer):
        self._write_mimetype(writer)
        self._write_items(writer)
        self._write_container_xml(writer)
        self._write_content_opf(writer)
        self._write_toc_ncx(writer)

    def make_epub(self, filename):
        """Create the .epub file.
        Args:
            filename (text): the full filename, e.g. '/path/to/mybook.epub'
        """
        fzip = zipfile.ZipFile(filename, 'w')
        self.write_all(ZipWriter(self, fzip))
        fzip.close()

    def make_epub_unpacked(self, root_dir):
        """Create all the files for the epub archive in a directory structure (unpacked).
        Args:
            root_dir (text): the directory where to put the epub content
        """
        self.root_dir = root_dir
        self.write_all(FileWriter(self))

class FileWriter(FrozenClass):
    """Writes text to a file.
    """
    def __init__(self, ebook):
        self.ebook = ebook
        self._freeze()

    def write(self, path, data, binary = False, compress_type=zipfile.ZIP_STORED):
        fullpath = os.path.join(self.ebook.root_dir, path)
        dirpath = os.path.split(fullpath)[0]
        try:
            os.makedirs(dirpath)
        except OSError:
            pass
        if binary:
            fout = io.open(fullpath, 'wb')
        else:
            fout = io.open(fullpath, 'w', encoding='UTF-8')
        fout.write(data)
        fout.close()

class ZipWriter(FrozenClass):
    """Writes text inside a zip file.
    """
    def __init__(self, ebook, zipfile):
        self.zipfile = zipfile
        self.ebook = ebook
        self._freeze()

    def write(self, path, data, binary = False, compress_type=zipfile.ZIP_STORED):
        if not binary:
            data = data.encode('UTF-8')
        self.zipfile.writestr(path, data, compress_type)

def get_user_agent():
    return "litepubify {}".format(VERSION)

def info(msg):
    """Helper function to output information messages, as long as they haven't
    been silenced.
    """
    if not args.silent:
        print(msg)

def verbose(msg):
    """Helper function to output verbose messages in case they have been activated.
    """
    if not args.silent and (args.verbose or args.debug):
        print(msg)

def debug(msg):
    """Helper function to output debug messages in case they have been activated.
    """
    if not args.silent and args.debug:
        print(msg)

def warning(msg):
    """Helper function to issue a warning.
    """
    print("Warning: "+msg)

def error(msg):
    """Helper function to raise an error.
    """
    if isinstance(msg, text_type):
        msg = msg.encode('UTF-8')
    raise Exception(msg)

CONTAINER_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

CONTENT_TEMPLATE = """<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf"
            xmlns:dc="http://purl.org/dc/elements/1.1/"
            unique-identifier="bookid" version="2.0">
  <metadata>
    <dc:title>{title}</dc:title>
    <dc:creator>{creator}</dc:creator>
    <dc:identifier id="bookid">urn:uuid:{uuid}</dc:identifier>
    <dc:language>en-US</dc:language>{metacover}
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>{manifest}
  </manifest>
  <spine toc="ncx">{spine}
  </spine>{guide}
</package>"""

META_COVER_TEMPLATE = """
    <meta name="cover" content="cover"/>"""

MANIFEST_ITEM_TEMPLATE = """
    <item id="{id}" href="{filename}" media-type="{mediatype}"/>"""

SPINE_ITEM_TEMPLATE = """
    <itemref idref="{id}"{add}/>"""

GUIDE_TEMPLATE = """
  <guide>
    <reference href="cover.html" title="cover" type="cover" />
  </guide>"""

NCX_TEMPLATE = """<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
                 "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid"
content="urn:uuid:{uuid}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>{title}</text>
  </docTitle>
  <navMap>{nav}
  </navMap>
</ncx>"""

NAV_POINT_TEMPLATE = """
    <navPoint id="{id}" playOrder="{playorder}">
      <navLabel>
        <text>{title}</text>
      </navLabel>
      <content src="{filename}"/>
    </navPoint>"""

TXT_HTML_TEMPLATE = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>{title}</title>
  </head>
  <body>
{content}
  </body>
</html>"""

COVER_TEMPLATE = """<h1 style="text-align: center">{title}</h1>
<p style="text-align: center">by <i>{author}</i></p>
"""

TITLE_TEMPLATE = """<h2>{title}</h2>
<p>by <i>{author}</i></p>
<hr />
"""

main()








