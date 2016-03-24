#!/usr/bin/python2
# -*- coding: utf-8 -*-

"""
lm: list movies (or list media)

Copyright (C) 2012  Guillaume Garchery 	(polluxxx@gmail.com)
Copyright (C) 2010  Jérôme Poisson 	(goffi@goffi.org)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import os
import re
import sys
import time
import imdb
import zlib
import struct
import base64
import codecs
import locale
import logging
import cPickle
import argparse
import xmlrpclib
from difflib import SequenceMatcher
from unicodedata import normalize

reload(sys)
sys.setdefaultencoding('utf8')

# windows terminal coloration
from platform import system
if system().lower()=="windows":
    try:
        import colorama
        colorama.init()
    except:
        pass

# ********** GLOBAL VARIABLES ************************************************
NAME    = 'lm (list movies)'
VERSION	= '0.4'
ABOUT 	= NAME+" v"+VERSION+"""

---
"""+NAME+""" Copyrights:
(C) 2012  Guillaume Garchery 	<http://redrises.blogspot.com>
(C) 2010  Jérôme Poisson 	<http://www.goffi.org>
This program comes with ABSOLUTELY NO WARRANTY;
This is free software, and you are welcome to redistribute it
under certain conditions.
---
This software is a command line tool for listing movies using IMDb metadata
"""

# User agent is essential to request opensubtitles
# be sure to update it before any change
OPENSUBTITLE_USER_AGENT = "lm v2.0"
OPENSUBTITLE_DOMAIN     = "http://api.opensubtitles.org/xml-rpc"

# ********** LOGGiING ********************************************************
class NullHandler(logging.Handler):
    def emit(self, record):
        pass

LOG_FORMAT = "%(asctime)-6s: %(name)s - %(levelname)s - %(message)s"
logging.basicConfig( format=LOG_FORMAT, level=logging.ERROR)
logger = logging.getLogger("LM_UTIL")

def consoleLogging( format, level):
    logger.setLevel( level )

def fileLogging( format, level, filename):
    formatter = logging.Formatter( format )
    fileLogger = logging.FileHandler(filename=filename, mode="w")
    fileLogger.setFormatter(formatter)
    logger.setLevel( level )
    logger.addHandler(fileLogger)

# ********** UTILITY FUNCTIONS ***********************************************
# returns all files in dir (and subdir if recurs==True) filter
# by specified extensions
def filelist( dir, recurs=True, *ext):
    """ recursive listing of files in a directory matching extension """
    result, alist = [], []

    for f in os.listdir(dir):
        if not isinstance(f,unicode):
            logger.warning("%s filename not properly encoded" % f)
        else:
            alist.append( os.path.abspath(os.path.join(dir,f)) )

    result.extend( [ f for f in filter( os.path.isfile, alist ) \
        if (not ext or (os.path.splitext(f)[1].lower() in ext)) ] )
    if recurs:
        for f in [ d for d in alist if not os.path.isfile(d)]:
            if os.path.exists(f):
                result.extend( filelist( f, True, *ext) )
    return result

# opensubtitle hash function
def hashFile(name):
    try:

        longlongformat = 'q'  # long long
        bytesize = struct.calcsize(longlongformat)

        f = open(name, "rb")

        filesize = os.path.getsize(name)
        hash = filesize

        if filesize < 65536 * 2:
                return "SizeError"

        for x in range(65536/bytesize):
                buffer = f.read(bytesize)
                (l_value,)= struct.unpack(longlongformat, buffer)
                hash += l_value
                hash = hash & 0xFFFFFFFFFFFFFFFF #to remain as 64bit number

        f.seek(max(0,filesize-65536),0)
        for x in range(65536/bytesize):
                buffer = f.read(bytesize)
                (l_value,)= struct.unpack(longlongformat, buffer)
                hash += l_value
                hash = hash & 0xFFFFFFFFFFFFFFFF

        f.close()
        returnedhash =  "%016x" % hash
        return returnedhash

    except(IOError):
            return "IOError"

# keeps only ascii alpha numeric character
def alphanum( string, fill=' ' ):
    string = to_ascii( string )
    return re.sub( '[^a-zA-Z0-9]{1,}', fill, string ).strip()

def to_ascii( string ):
    if not isinstance( string, unicode ):
        string = unicode(string,'cp850')
    return normalize( 'NFKD', string ).encode('ascii', 'ignore')

# boolean yes / no raw_input
def boolean_input(msg):
    res = None
    while res not in ['y','n']:
        res = raw_input( msg + ' (y/n):').lower()
    return( res=='y')

# ********** ARGUMENTS HANDLER ***********************************************
def parse_arguments():

    parser = argparse.ArgumentParser(description=ABOUT)

    parser.add_argument('--top', action="store_true",
            help="Use top250 instead of files")
    parser.add_argument('--movielist', action="store_true",
            help="Use titles from specified file instead of files")
    parser.add_argument('-a','--alphabetical',
            action="store_true",default=False,
            help="sort by alphabetical order of title instead of rating")
    parser.add_argument('-r','--reverse',
            action="store_true", default=False,
            help="show media in reverse order")
    parser.add_argument('-d','--delete_cache',
            action="store_true", default=False,
            help="delete targeted files in cache. A confirmation is \
                    asked. To delete all cache use lm.py cache -d")
    parser.add_argument('-f','--filter',
            help="filter @keyword:filter1,filter2@keyword2:filter3, \
                    @genre:action@size:+500 will look at action movies \
                    bigger than 500Mb, @size:-100 will look at movies\
                    smaller than 100Mb, @unsure will filter files not\
                    found on opensubtitles with a bad match to imdb \
                    movies")
    parser.add_argument('-l','--long', action="store_true",
            help="Show long information on movie")
    parser.add_argument('-L','--very-long', action="store_true",
            help="Show full information on movie")
    parser.add_argument('-o','--outline', action="store_true",
            help="Show plot outline")
    parser.add_argument('--confirm', default=False,
            action="store_true",
            help="Manually confirm/search selected movies. May be usefull\
                    to ask for unsure movies only (ie with bad imdb match)\
                    with '-f @unsure' argument")
    parser.add_argument('--upload', default=False,
            action="store_true",
            help="Individually upload hash info to opensubtitles. Only\
                    files without opensubtitles correspondance will be\
                    selected")
    parser.add_argument('--download',
            help="Look for available subtitles for specific language.\
                    Use ISO639-1 codes, like eng/fre/dut/ger")
    parser.add_argument('-s', '--show-imdb', action="store_true",
            help="Show IMDb webpage of each movie in default navigator\
                    (don't use if you're listing a lot of files!)")
    parser.add_argument('-S', '--show', action="store_true",
            help="Show a sumup html page, with covers and usefull links")
    parser.add_argument('--html-build', action="store_true",
            help="Build HTML sumup page without display")
    parser.add_argument( 'files', nargs="*",
            help="media files to check, by default looks at current dir")
    parser.add_argument('--reset', action="store_true",
            help="Delete all cache files (use it when corrupted")
    parser.add_argument('--debug', action="store_true",
            help="Display debug logging info, and write log message in\
                     ~/.lm/lm_log.txt")
    parser.add_argument('--version', action="store_true",
            help="Display current version")

    options = parser.parse_args()

    args = options.files


    if options.delete_cache +  options.confirm + \
            options.upload >1 :
        logger.error("please choose ONE only from upload/confirm/delete")
        exit(2)

    if options.confirm or options.upload:
        options.long = True

    # take care of the 'unsure' filter
    if options.filter:
        try:
            options.filter_dict = decode_filter_phrase( options.filter )

        except FilterParsingError as e:
            logger.error( str(e) )
            exit(2)

    if options.show or options.show_imdb:
        import webbrowser
        global webbrowser

    if not args:
        if options.confirm:
            logger.error("You have to specify give files when using --confirm")
            exit(2)
        args=[u'.']

    return( (options, args) )

def decode_filter_phrase( filter_phrase ):
    # transforms the filter param argument to a more convenient form
    result = {}
    filter_types = {    'genre':'genre',
                     'director':'director',
                        'actor':'cast',
                        'runtime':'runtime',
                        'year':'year',
                        'rating':'rating',
                         'size':'size',
                      'country':'countries',
                       'unsure':'unsure' }

    filter_phrase = filter_phrase.lower()

    if filter_phrase[0] != "@":
        raise FilterParsingError("filter should begin with @")

    flt1 = filter_phrase.split('@')

    for f in flt1[1:]:

        fs = f.split(":")
        if len(fs)==1 and fs[0]=="unsure": fs.append("")

        if len(fs)!=2: raise FilterParsingError

        ftype, fkeys = fs

        if not filter_types.has_key(ftype):
            raise FilterParsingError("Keyword not recognized")
        else:
            ftype = filter_types[ftype]

        fkeys = fkeys.split(",")

        if ftype=="size":
            try:
               fkeys = [float(k) for k in fkeys]
            except:
                raise FilterParsingError("Wrong syntax for size filtering")

        if not result.has_key(ftype): result[ftype] = []

        result[ftype].extend( fkeys )

    return result



# ********** Exceptions ******************************************************
class FilterParsingError(Exception):

    def __init__(self, msg=None):
        self.msg = msg

    def __str__(self):
        res = "Error when parsing filter, please read help for syntax"
        if self.msg:
            res += (" [detail: %s]" % self.msg)
        return( res )

class LoginError(Exception):
    def __init__(self,msg=None):
        self.msg = msg

    def __str__(self):
        res = "LoginError"
        if self.msg:
            res += (" [detail: %s]" % self.msg)
        return res

class OpensubtitlesError(Exception):
    pass

# fixed keys dictionary, to avoid error on small "key/value" data storage
class store(dict):

    def __init__(self,*args,**kwargs):

        self.static  = False
        self.update( *args, **kwargs )
        self.static  = True

    def __getitem__(self, key):
        if dict.__contains__(self,key):
            return dict.__getitem__(self,key)
        else:
            return None

    def __setitem__(self, key, val):
        if dict.__contains__(self,key) or not self.static:
            dict.__setitem__(self,key,val)
        else:
            raise KeyError, str(key) + " not in store keys"

    def update(self, *args, **kwargs):
        for k, v in dict( *args, **kwargs ).iteritems():
            self[k] = v


# ********** MAIN CLASS ******************************************************
class ListMovies():

    order_alpha     = False
    order_reverse   = False
    filter_phrase   = None

    disp_long       = False
    disp_very_long  = False
    disp_outline    = False

    def __init__( self, options=None, level=logging.ERROR ):

        if options:
            self.order_alpha = options.alphabetical
            self.order_reverse = options.reverse
            self.filter_phrase = options.filter
            self.filter_dict = options.filter_dict if options.filter else None
            self.disp_long = options.long
            self.disp_very_long = options.very_long
            self.disp_outline = options.outline

        self.log = logging.getLogger("LM")
        self.log.addHandler( NullHandler() )
        self.log.setLevel( level )
        self.log.info( "LM initialization" )

        # create hidden directory if needed at ~/.lm/
        cache_dir = os.path.expanduser('~/.lm')
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

        self.cache_path_fn = os.path.join( cache_dir, 'cache_path')
        self.cache_imdb_fn = os.path.join( cache_dir, 'cache_imdb')

        # html output sumup file
        self.html_fn  = os.path.join( cache_dir, 'html_sumup.html')

        self.load_cache_path()
        self.load_cache_imdb()

        self.i = imdb.IMDb()

        # opensubtitles XMLRPC server and tokern
        self.server = None
        self.token  = None

        # terminal coloration
        self.RED    = "\033[00;31m"
        self.YELLOW = "\033[00;33m"
        self.MAGEN  = "\033[01;35m"
        self.BLUE   = "\033[01;34m"
        self.END    = '\033[0m'

        # video files common extension
        # http://trac.opensubtitles.org/projects/opensubtitles/wiki/
        self.file_ext = [
                     '.3g2','.3gp','.3gp2','.3gpp','.60d','.ajp','.asf',
                     '.asx','.avchd','.avi','.bik','.bix','.box','.cam',
                     '.dat','.divx','.dmf','.dv','.dvr-ms','.evo','flc',
                     '.fli','.flic','.flv','.flx','.gvi','.gvp','.h264',
                     '.m1v','.m2p','.m2ts','.m2v','.m4e','.m4v','.mjp',
                     '.mjpeg','.mjpg','.mkv','.moov','.mov','.movhd',
                     '.movie','.movx','.mp4','.mpe','.mpeg','.mpg','.mpv',
                     '.mpv2','.mxf','.nsv','.nut','.ogg','.ogm','.omf',
                     '.ps','.qt','.ram','.rm','.rmvb','.swf','.ts','.vfw',
                     '.vid','.video','.viv','.vivo','.vob','.vro','.wm',
                     '.wmv','.wmx','.wrap','.wvx','.wx','.x264','.xvid']
        self.file_ext = [ unicode(ext) for ext in self.file_ext ]

        self.forbidden_words = ['divx','dvdrip','xvid','ts','dvdscr',
                     'cam','dvdscr','xvid','aac','r5']

        self.default_imdb = {
            'm_title'             : None,
            'm_canonical_title'   : None,
            'm_runtime'           : 0,
            'm_rating'            : None,
            'm_year'              : None,
            'm_genre'             : None,
            'm_countries'         : None,
            'm_director'          : None,
            'm_short_summary'     : None,
            'm_summary'           : None,
            'm_cast'              : None,
            'm_votes'             : None,
            'm_cover'             : None,
            'imdb_id'             : None,
            'm_last_update'       : None,
        }

        self.default_path = {
            'imdb_check'          : 0,
            'imdb_id'       : None,
            'file_hash'     : None,
            'g_title'       : None,
            'g_year'        : None,
            'g_unsure'      : False,
            'bytesize'      : None,
            'last_update'   : 0,
            'o_year'        : None,
            'o_check'       : 0,
            'o_title'       : None,
            }

    # ********** CACHE HANDLERS **********************************************
    def load_cache_path(self):
        self.log.info("loading cache_path")
        try:
            with open(self.cache_path_fn,'r') as f:
                self.cache_path = cPickle.load(f)
            self.log.info("cache_path file loaded successfully")
        except:
            self.log.debug("cache_path not loaded ->  empty initilazation")
            self.cache_path = store()
            self.cache_path.static = False

    def _save_cache_path(self):
        self.log.info("saving cache_path")
        with open(self.cache_path_fn,'w') as f:
            cPickle.dump(self.cache_path,f)
        self.log.info("cache_path saved")

    def load_cache_imdb(self):
        self.log.info("loading cache_imdb")
        try:
            with open(self.cache_imdb_fn,'r') as f:
                self.cache_imdb = cPickle.load(f)
            self.log.info("cache_imdb file loaded successfully")
        except:
            self.log.debug("cache_imdb not loaded ->  empty initilazation")
            self.cache_imdb = store()
            self.cache_imdb.static = False

    def _save_cache_imdb(self):
        self.log.info("saving cache_imdb")
        with open(self.cache_imdb_fn,'w') as f:
            cPickle.dump(self.cache_imdb,f)
        self.log.info("cache_imdb saved")

    def _sync_cache(self):
    # delete self.cache_path items pointing whose hash isnt pointing
    # to an self.cache_imdb key
        self.log.info("synchronizing caches")
        files = [ f for f, v in self.cache_path.iteritems() if \
                    not self.cache_imdb.has_key(v['imdb_id']) \
                    ]
        for f in files:
            del self.cache_path[f]

    def save_cache(self):
    # save cache function
    # save both at same time, after 'consistency' check:
    # every path from cache_path should point to an hash in cache_imdb

        self.log.info("saving caches")
        # self._sync_cache() # TODO XXX
        self._save_cache_path()
        self._save_cache_imdb()

    def delete_cache( self, files ):
    # delete a list of files in cache
    # -> obviously deleted in cache_path
    # -> but we delete also every hash (cache_imdb)
    # not pointed by a file anymore

        cache_path = self.cache_path
        cache_imdb = self.cache_imdb

        files = [ f for f in files if cache_path.has_key(f)]
        self.log.debug("%d entries to delete from cache_path" % len(files) )

        if len(files)>0:
            for f in files:
                print( os.path.basename(f) )
            print("*** trying to delete %i files from cache" % len(files))
            confirm = boolean_input('Please confirm cache deletion')

            if confirm:
                for f in files:
                    imdb_id = cache_path[f]['imdb_id']
                    if cache_imdb.has_key(imdb_id):
                        del cache_imdb[imdb_id]
                    del cache_path[f]

                self.save_cache()

        else:
            print("no file to delete")

    def reset_cache_files(self):
        confirm = boolean_input("Confirm cache files deletion?")
        if confirm:
            if os.path.exists(self.cache_path_fn):
                os.remove(self.cache_path_fn)
            if os.path.exists(self.cache_imdb_fn):
                os.remove(self.cache_imdb_fn)
            if os.path.exists(self.html_fn):
                os.remove(self.html_fn)

    #
    def flush_out_str(self, out_str):
        sys.stdout.write( (out_str+'\r').encode('utf-8') )
        sys.stdout.flush()

    # ********** CACHE UPDATERS  *********************************************
    # When you update caches (cache_path, and cache_imdb) order matters
    #
    # A/ first get files to consider
    # then run:
    #   1/ update_caches_with_paths
    #       this function will update cache_path and cache_imdb keys
    #       and will set default keys/values
    #   2/ update_cache_imdb_opensubtitles, to search for known hash
    #   3/ update_cache_imdb_metadata, to complete metadata from imdb

    def update_caches_with_paths( self, abs_paths ):
    # Update cache_path with a list of new paths (abs_paths)
    # check if already in cache, and if cached version update
    # is more recent than last file modification.
    # i.e. if you modified you file after your last 'lm' call
    # 'lm' will re-hash your file
    # if hash error, None is stored in cache

        cache_path = self.cache_path
        cache_imdb = self.cache_imdb
        for path in abs_paths:

            if not( cache_path.has_key(path) and \
                    (not os.path.exists(path) or \
                    os.path.getmtime(path) < cache_path[path]['last_update'])):

                self.log.info("adding new path to cache: %s" % path)
                file_hash = hashFile(path)

                if file_hash in ['SizeError','IOError']: file_hash = None
                cache_path[path] = store( self.default_path )
                cache_path[path].update( {'file_hash':file_hash,
                                   'last_update':time.time(),
                                   'bytesize': os.path.getsize(path) \
                                           if os.path.exists(path) else 0} )

        self.save_cache()

    def update_caches_with_top( self, num ):
        cache_path = self.cache_path
        cache_imdb = self.cache_imdb

        try:
            movie_list = self.i.get_top250_movies()[0:num]
            if not movie_list:
                self.log.warning("failed to get top250 from IMDB")
                return
        except imdb.IMDbError, e:
            print( "Connexion error")
            #print e
            return

        for idx, movie in enumerate(movie_list):
            key = "top" + str(idx+1)
            imdb_id = movie.getID()
            if not( cache_path.has_key(key) and \
                    cache_path[key]['imdb_id'] == imdb_id ):
                last_imdb_id = None

                self.log.info("adding new top to cache: %s" % key)

                if cache_path.has_key(key):
                    last_imdb_id = cache_path[key]['imdb_id'];

                cache_path[key] = store( self.default_path )
                cache_path[key].update( {'imdb_id':imdb_id } )

                # setting default keys.values in cache
                if not cache_imdb.has_key(imdb_id):
                    self.log.debug("adding hash entry %s for file: %s" % ( \
                            str(imdb_id), key ) )

                    cache_imdb[imdb_id] = store( self.default_imdb )
                    cache_imdb[imdb_id]['imdb_id'] = imdb_id

                self.__get_metadata(key) 

                if last_imdb_id:
                    result = self.cache_imdb[imdb_id]
                    last_result = self.cache_imdb[last_imdb_id]
                    print("%s: %s (was %s)" %
                            (key, result['m_title'], last_result['m_title']))

        self.save_cache()

    def update_cache_imdb_opensubtitles(self):
    # Update cache_imdb opensubtitles info
    # For movies which hash was not found in opensubtitles, will be tried
    # again only 6 hours after

        cache_path = self.cache_path
        cache_imdb = self.cache_imdb
        paths = [ path for path in cache_path.keys() if path and
                cache_path[path]['file_hash'] and
                not cache_path[path]['o_title'] and 
                cache_path[path]['o_check'] < time.time()-3600*6 ]

        file_hashs = [ cache_path[path]['file_hash'] for path in paths ]
        data = self.get_info_from_opensubtitles( file_hashs )

        for path in paths :
            file_hash = cache_path[path]['file_hash'] 

            now = time.time()
            cache_path[path]['o_check'] = now

            if data.has_key(file_hash):
                info = data[file_hash]
                if info:
                    try:
                        imdb_id = info['MovieImdbID']
                        open_info = {'imdb_id':info['MovieImdbID'],
                                       'o_title':info['MovieName'],
                                        'o_year':info['MovieYear']}
                        cache_path[path].update( open_info )
                        cache_imdb[imdb_id] = store( self.default_imdb )
                        cache_imdb[imdb_id]['imdb_id'] = imdb_id

                    except:
                        self.log.debug("faild to update (%s) open info" +\
                                " with open answer %s " % (path,str(info)) )
                        pass

        if len(paths)>0:
            self.save_cache()

    # *********** OPENSUBTITLES CONNECTIONS **********************************
    def status_ok(self, ans):
        status = False
        try:
            if ans.has_key("status") and ans["status"] == "200 OK":
                self.log.debug("OpenSubtitles answer status OK")
                status = True
            else:
                self.log.warning("OpenSubtitles answer status DOWN")

        except Exception, e:
            self.log.error(str(e))

        finally:
            return( status )

    def login(self, user="", password=""):
        try:
            server = xmlrpclib.ServerProxy(OPENSUBTITLE_DOMAIN)
            log    = server.LogIn(user,password,'en',OPENSUBTITLE_USER_AGENT)

            if self.status_ok(log):
                self.log.debug("OpenSubtitles login OK")
                self.server = server
                self.token  = log['token']
            else:
                raise LoginError(str(log))

        except LoginError, e:
            self.log.warning( str(e)  )

        except Exception, e:
            self.log.error("OpenSubtitles login process DOWN: %s" % str(e))


    def logout(self):
        if self.token:
            try:
                self.server.LogOut(self.token)
                self.log.debug("OpenSubtitles logout OK")
            except Exception, e:
                self.log.warning("OpenSubtitles logout process DOWN, %s" % \
                        str(e))

    # retrive general info for a list of movie hash
    def get_info_from_opensubtitles( self, file_hashs ):
            data = {}

            if len(file_hashs)>0:
                self.log.info("request OpenSubtitle info for %d hashes" %\
                        len(file_hashs))
                try:
                    self.login()
                    for k in range( len(file_hashs)/150+1 ):
                        res = self.server.CheckMovieHash( self.token,
                                file_hashs[150*k:(150*(k+1))] )
                        data.update( res['data'] )
                    self.logout()
                except LoginError:
                    self.log.debug("Error when retrieving hash " + \
                            "from opensubtitles")
                    pass

                for k, v in data.iteritems():
                    if len(v)==0: data[k]=None

            return(data)

    def update_cache_imdb_metadata(self):
    # Update metadata from IMDB for
    # If movie hash found in opensubtitles:
    # we already know the imdb id -> simple call
    # Else:
    # we use hand design algorithm based on filename to detect imdb id.
    # 1/ guess the title with filename
    # 2/ call imdb with this query
    # 3/ look for the best local title match
    #
    # If movie hash not found in opensubtitle and file modified after
    # our last imdb call -> we call imdb again

        cache_path = self.cache_path
        cache_imdb = self.cache_imdb
        paths = []
        for path,info in cache_path.iteritems():
            if info:
                c_time = info['cache_time']
                updt_after   = not info['imdb_id'] and info['imdb_check']<c_time

                if not info['imdb_check'] or updt_after:
                    paths.append(path)

        idx, last_len, total = 1, 0, len(paths)

        for path in paths:
            self.log.info("get metadata for path: %s" % path )
            out_str = u"Getting metadata: [%(index)i/%(nb_movies)i] "
            out_str = out_str % {'index':idx,'nb_movies':total}
            if len(out_str) < last_len:
                sys.stdout.write(' '*last_len+'\r')
            self.flush_out_str(out_str)

            self.__get_metadata(path)
            cache_path[path]['imdb_check'] = time.time()

            if idx % 10 == 0:
                self.save_cache()
            idx += 1

        if len(paths)>0:
            self.save_cache()
            self.flush_out_str(' '*last_len+'\r')

    def find_imdb_result(self, guess, path):
        cache_path = self.cache_path
        cache_imdb = self.cache_imdb

        results = self.i.search_movie( guess['g_title'] )

        if results:
            self.log.info("finding best match in answers")
            best_result, unsure = self.best_match( guess['g_title'],
                    guess['g_year'], results)

            self.log.debug("best result for %s: %s" % \
                    (guess['g_title'], best_result.get('title')))

            cache_path[path]['g_unsure'] = unsure
            self.i.update(best_result)
            imdb_id = best_result.movieID
            cache_path[path]['imdb_id'] = imdb_id

            # setting default keys.values in cache
            self.log.debug("adding hash entry %s for file: %s" % ( \
                    str(imdb_id), path ) )

            cache_imdb[imdb_id] = store( self.default_imdb )
            self.__fill_metadata( imdb_id, best_result)
        else:
            self.log.info("no result from IMDb, empty metadata")
            cache_path[path]['g_unsure'] = True

    def __get_metadata(self, path):
    # "Get metadata for files not already in cache
    # @param files: list of filenames (path or basenames)

        cache_path = self.cache_path
        imdb_id    = None

        #XXX todo meme cache pour top et path, appele name
        try:
            # if we have an imdb_id for this hash
            imdb_id = cache_path[path]['imdb_id']

            if imdb_id:
                self.log.info("IMDb id already found %s" % imdb_id)
                result = self.i.get_movie(imdb_id)
                if result:
                    self.__fill_metadata( imdb_id, result )
                else:
                    self.log.warning("failed to get movie info from IMDB")

            else:
                # we need to guess a title, from a file pointing to this hash
                self.log.info("no IMDb id stored")
                if cache_path[path]['bytesize']:
                    guess = self.guessed_title_year( path )
                else:
                    guess = { 'g_title':path.strip(), 'g_year': None }
                self.log.debug("info guessed from filaneme %s" % str(guess) )
                cache_path[path].update( guess )
                self.find_imdb_result(guess, path)

        except imdb.IMDbError, e:
            print( "Connection error, current movie: [%s]" % \
                    imdb_id if imdb_id else guess['g_title'] )
            print e
            self.save_cache()
            sys.exit(2)


    # ********** UNKNOW HASH MATCHER *****************************************
    def best_match(self, guess_title, guess_year, results=None):
        # Check match between the found movie and original filename

        if not results:
            results = self.i.search_movie( guess_title )

        _guessed_title = alphanum( guess_title ).lower()
        _guessed_year  = guess_year

        _results = [ r for r in results if isinstance(r,imdb.Movie.Movie) ]
        if _guessed_year:
            _results = [ r for r in _results if r.has_key('year') \
                                        and r['year'] == _guessed_year ]

        _best_ratio  = 0
        _best_result = None

        for r in _results:

            _list_titles  = [ alphanum(title.split('::')[0]).lower() \
                                    for title in (r.get('akas') or [])]
            _list_titles += [ alphanum(r.get('title')).lower() ]

            for other_title in _list_titles:
                cur_ratio = SequenceMatcher(None,
                            other_title,_guessed_title).ratio()

                if cur_ratio > _best_ratio:
                    _best_ratio, _best_result = cur_ratio, r
                    self.log.info("ratio ==> %s (for [%s]) %f" % \
                                    ( other_title, _guessed_title, cur_ratio))

        unsure = _best_ratio < 0.7

        if _best_ratio < 0.7 and _guessed_year:
            self.log.info( "ratio <0.7 & year, we retry on base results")
            _best_result, unsure = self.best_match(guess_title,None,results)

        return _best_result, unsure

    def guessed_title_year( self, files ):
    # Try to guess title from movie filename
    # @param files: filename to parse

        # we take everything before information in bracket
        # or square bracket, as these info are usually not part of the title
        title_reg = re.compile('^[^[(]+')
        # the year is most of time placed between
        # the title and other information, we are intersted by what is before
        before_year_reg = re.compile(r'(.*)[12][1089][0-9]{2}.*')
        # in some case, we have the title with lowercases,
        # and other info (e.g. language) fully uppercase, this regex test this
        upper_reg = re.compile(r'(^.+?)[A-Z]{2}.*')

        init_title = os.path.splitext(os.path.basename(files))[0]

        tmp_title = alphanum(
                (re.findall(title_reg,init_title) or [init_title])[0] )
        # 2nd regex
        tmp_title = re.sub(before_year_reg, r'\1', tmp_title) or tmp_title
        # 3rd regex
        title     = re.sub(upper_reg,r'\1', tmp_title) or tmp_title

        # In some cases, the previous regex give a wrong title,
        # we try to detect this by cancelling too short title
        if len(title) < 3:
            title = tmp_title

        title = title.strip().lower()

        #we now remove forbidden words
        title_words = title.split(' ')
        for forbidden in self.forbidden_words:
                if forbidden in title_words:
                    title_words.remove(forbidden)
        title = ' '.join(title_words)
        guessed_year = re.findall('([12][1089][0-9]{2})', init_title) or None
        guessed_year = int(guessed_year[0]) if guessed_year else None
        if guessed_year < 1800 or 2100 < guessed_year:
            guessed_year = None

        return {'g_title':title.strip(), 'g_year':guessed_year}
  
    def get_runtime( self, runtime_list ):
    # Extract the first runtime found from runtime_list
        return runtime_list[0].split('::')[0].split(':')[-1]


    def __fill_metadata(self, imdb_id, found):
    # Fill metadata for one movie
    # @param imdb_id: current hash to update
    # @param found: the imdb movie object selected

        current = self.cache_imdb[imdb_id]

        current['m_last_update'] = time.time()

        if found:
            current['imdb_id']    = found.movieID
            current['m_title'] = found.get('title')
            current['m_canonical_title']=found.get('smart canonical title')
            current['m_runtime'] = found.get('runtime')
            current['m_rating'] = found.get('rating')
            current['m_year']   = found.get('year')
            current['m_genre']  = found.get('genre') or []
            current['m_countries'] = found.get('countries') or []
            current['m_director'] = [director.get('name') for director in
                    (found.get('director') or [])]
            current['m_short_summary'] = found.get('plot outline')
            current['m_summary'] = (found.get('plot') or [''])[0]
            current['m_cast'] = [ actor.get('name') for actor in
                    (found.get('cast') or [])]
            current['m_votes'] = found.get('votes')
            current['m_cover'] = found.get('cover url') or []

        else:
            current.update({
                    'imdb_id':'000000', 'm_title':'___NOTFOUND___',
                    'm_canonical_title':'___NOTFOUND___',
                    'm_genre':[],'m_countries':[],
                    'm_director':[], 'm_cast':[], 'm_cover':[],
                    'm_votes':0, 'm_summary':'.'*20,'m_rating':0,
                    'm_runtime':[0],'m_year':1900,'m_short_summary':'.'*20})


    # ********** MANUAL CONFIRMATION *****************************************
    def manual_confirm( self, files ):
        """ @param files: list of files to be confirmed by hand """

        update_count = 0
        for f in files:
            out_str =  "\n***************\n"
            out_str += "File to confirm\n"
            out_str += "***************\n"
            out_str += "absolute path : %s\n"
            out_str += "basename      : %s\n"
            out_str = out_str % ( f, os.path.basename(f) )
            print( out_str )

            update_count += self.__manual_confirm( f )
            print("\n%i movies updated" % update_count )


    def __manual_confirm( self, f, ask=False ):
    # Go through interaction with user to confirm a file with
    # either an IMDB ID or a title or year
    # @param f: an absolute path
    # @param ask: boolean, do you let the chance to exit the process?

        if ask:
            if not boolean_input('Try again for this movie?'):
                return(False)

        imdb = self.cache_path[f]['imdb_id']
        # TODO if imdb vaut None

        try:

            if self.cache_imdb[imdb]['imdb_id'] != '000000':
                self.pretty_print(f)
                confirm = boolean_input("Do you confirm stored info?")
                if confirm:
                    self.cache_path[f]['g_unsure'] = False
                    return( True )

            input_id = boolean_input("Will you provide an IMDb id?")
            if input_id:
                imdb_id =raw_input('please enter the IMDb id for this movie:')
                result = self.i.get_movie(imdb_id)
            else:
                title =raw_input('please enter movie title:')
                year  =raw_input('please enter year, leave blank if unknown:')
                if year=='':
                    year = None
                result, unsure = self.best_match( title, year )

            if result:
                print( '--> movie found title: %s' % result['title'] )
                print( '--> movie found  year: %s' % result['year'] )
                agree = boolean_input('Confirm this result?')
                if agree:
                    self.__fill_metadata(imdb, result)
                    self.cache_imdb[imdb].update(\
                        { 'g_title':result['title'],
                          'g_year':result['year'] })
                    self.cache_path[f]['g_unsure'] = False
                    self.save_cache()
                    print("movie saved")
                    return( True )
                else:
                    return( self.__manual_confirm( f, ask=True ) )
            else:
                print( '--> nothing found!')
                return( self.__manual_confirm( f, ask=True ) )

        except imdb.IMDbError, e:
            print( "Connexion error")
            print e
            return( self.__manual_confirm( f, ask=True ) )

    # ********** UPLOAD HASH TO OPENSUBTITLES ********************************
    def upload_to_opensubtitles(self, files):
    # filter a list of files to get only those which hash was not
    # found in opensubtitles, and will ask the user if he wants to
    # send the couple (imdb_id, hash) to opensubtitles.
    # @param files: a list of absolute path

        files = [ f for f in files if \
                    not self.cache_imdb[
                        self.cache_path[f]['hash']]['imdb_id']]
                    # TODO
        if len(files)>0:

            to_upload = []
            for f in files:

                file_hash = self.cache_path[f]['file_hash']
                if not file_hash:
                    continue
                imdb_id  = self.cache_path[f]['imdb_id']
                bytesize = str(self.cache_path[f]['bytesize'])

                self.pretty_print(f)
                msg = "Do you want to send hash info to opensubtitles?"
                insert = boolean_input(msg)
                if insert:
                    to_upload.append( { 'moviehash':file_hash,
                                    'moviebytesize':bytesize,
                                           'imdbid':imdb_id } )

            if len(to_upload)>0:
                try:
                    self.login()
                    call = self.server.InsertMovieHash( self.token, to_upload)
                    print( call )
                    logout = self.logout()

                    for v in to_upload:
                        h = v['moviehash']
                        self.cache_imdb[h]['o_check'] = None

                    self.save_cache()

                except Exception, e:
                    print("!!! Error when uploading hash to opensubtitles")
                    print( e )
                    if self.token:
                        logout = self.logout()
                        print( 'LOGOUT ***', logout )

    # ********** DOWNLOAD SUBTITLES FROM OPENSUBTITLES ***********************

    def download_subtitle(self, files, language):

        ref, query = self.download_subtitles_query( files, language )
        self.log.info("download subtitles query info %s" % str(query))

        if len(query)==0:
            self.log.info("all subtitles already downloaded!")
            return

        self.login()
        sub_refs = self.server.SearchSubtitles( self.token, query )

        if self.status_ok(sub_refs):
            if sub_refs['data'] != False:

                sub_ids = self.download_subtitles_filter(ref,sub_refs['data'])

                self.log.debug( "list of subtitlesid to donwload: %s" %\
                        ", ".join( sub_ids ) )

                subs     = self.download_subtitleids( sub_ids )
                if subs:
                    self.download_subtitles_write(ref,subs,language)

            else:
                self.log.info( "no subtitles found on OpenSubtitles %s" %\
                        str(sub_refs) )

        else:
            self.log.error("Subtitles download failed: %s" % str(sub_refs) )
#            raise OpensubtitlesError

        self.logout()

    def download_subtitles_query( self, files, lang ):
    # build a useful info dictionary and the list of queries
    # to be passed as argument to SearchSubtitles XMLRPC call

        # defining query to send
        ref, query = {}, []
        for f in files:

            # check if we already downloaded subtitles for this movie
            pattern = lang.upper() + "_LM[\d]{1,}\.srt$"
            filedir = os.path.dirname(f)
            old_subs = [ old for old in filelist(filedir,False) \
                    if re.search(pattern, old) ]

            h           = self.cache_path[f]['file_hash']
            osbtls      = self.cache_path[f]['imdb_id'] != None
            imdb_id     = self.cache_imdb[f]['imdb_id']
            byte_size   = self.cache_path[f]['bytesize']
            fn          = os.path.basename(f)

            if imdb_id and len(old_subs)==0:
                ref[f] = {'osbtls':osbtls, 'imdb_id':imdb_id,
                          'file':fn, 'file_hash':h }
                if osbtls:
                    query.append({ 'sublanguageid':lang,
                                       'moviehash':str(h),
                                   'moviebytesize':str(byte_size)})

                # even if hash is found in opensubtitles, we add
                # another query with imdb_id
                query.append({'sublanguageid':lang,'imdbid':imdb_id})

        return( (ref, query) )

    def download_subtitles_filter(self, ref, subs):
    # filters subs (list result of SearchSubtitles call)
    # and associates to each ref key, bests found subtitles (hash match)
    # or most downloaded subtitles
    # @param ref: output[0] of download_subtitles_query
    # @param subs: result['data'] of a SearchSubtitles XMLRPC call

        for k, v in ref.iteritems():

            keep = [ s for s in subs if s['MovieHash']==v['file_hash'] ]
            if len(keep)==0:
                keep = [ s for s in subs if s['IDMovieImdb']==
                        str(int(v['imdb_id'])) ]

            if len(keep)>0:
                keep.sort( key=lambda k: k['SubDownloadsCnt'],
                            reverse = True )

                v['keep'] = [ k['IDSubtitleFile'] for k in keep[0:3]]

            else:
                v['keep'] = None


        sub_ids = set([])
        for r, v in ref.iteritems():
            if v['keep']:
                sub_ids.update( v['keep'] )

        return(list(sub_ids))


    def download_subtitleids(self,sub_ids):
    # download, decode, and decompress a list of subtitles
    # @param sub_ids; list of subtitles id
        subs = None

        try:
            result = self.server.DownloadSubtitles(self.token,sub_ids)
        except Exception, e:
            self.log.error("OpenSubtitle download sub error" % str(e) )
            return( None )

        if self.status_ok(result):
            if result['data'] != 'False':
                subs = {}
                for sub in result['data']:
                    sub_d = base64.standard_b64decode(sub['data'])
                    sub_d = zlib.decompress( sub_d, 47 )
                    subs[sub['idsubtitlefile']] = sub_d

        return(subs)

    def download_subtitles_write(self,ref,subs,lang):
    # Write downloaded subtitles in movies directories with suffixe:
    # _LANG_LM[\d].srt
    # @param red: output of download_subititles_query
    # @param subs: list of decompressed subs [{'IDSubtitleFile':,'Data'}]

        for k, v in ref.iteritems():
            keep = v['keep']
            if keep:
                for i in range(len(keep)):
                    sub_file = os.path.splitext(k)[0] + '_' + lang.upper() + \
                            '_LM' + str(i+1) + '.srt'
                    f = codecs.open(sub_file,'wb')
                    f.write(subs[keep[i]])
                    f.close()

    # ********** GATHERING & FILTERING FILES *********************************
    def get_files(self,args):
    # Return files from args, if isdir -> recursive search
        result = []
        self.log.info("interpreting file/dir argument")

        if args[0]=='cache':
            self.log.info("loading all cache entries")
            result.extend( self.cache_path.keys() )
        else:
            for arg in args:
                if not arg:
                    continue        #we don't want empty arg
                encoding = locale.getdefaultlocale()[1]
                if encoding: arg = arg.decode( encoding )

                real_path = os.path.expanduser(arg)
                self.log.info("path expanded: %s" % real_path )

                if arg == real_path and not os.path.exists(arg):
                    real_path = os.path.join( os.getcwdu(), real_path )
                    self.log.info("real path: %s" % real_path )

                if os.path.isdir(real_path):
                    self.log.debug("dir to parse: %s" % real_path )
                    self.log.debug("dir var type: %s" % type(real_path) )

                    result.extend( filelist(
                        real_path, True, *self.file_ext ) )
                elif os.path.isfile(real_path):
                    result.append(arg)

        result = [ r for r in result if \
                os.path.exists(r) and os.path.getsize(r)>0L ]

        return result

    def user_filter(self, files):
    # Filter movies according to user given arguments
        self.log.info("number of files before filtering: %d" % len(files))
        filt = self.filter_phrase
        try:
            while filt:

                if filt[0]!='@':
                    raise FilterParsingError
                end = filt.find(':')

                if end == -1:
                    raise FilterParsingError
                filter_type = filt[1:end]

                if not filter_type in ['genre','director','actor','size',
                       'runtime', 'year', 'rating', 'country','unsure']:
                    raise FilterParsingError

                if filter_type=="actor":
                    filter_type='cast'
                elif filter_type=="country":
                    filter_type="countries"
                filt = filt[end+1:]
                end = filt.find('@')

                if end == -1:
                    end = None
                keys = set([key.lower() for key in filt[:end].split(',')])
                filt = filt[end:] if end else ''

                if filter_type =='size':
                    self.log.info("filtering by size")

                    if (len(keys)>1):
                        raise FilterParsingError
                    try:
                        keys = list(keys)[0]

                        if keys[0] in ['-','+']:
                            sign = 1 if keys[0] == '+' else -1
                            keys = keys[1:]
                        else:
                            sign = 1

                        keys = float(keys)
                        self.log.info("filtering key: %s%f" % \
                                ( "> " if sign==1 else "< ", keys))
                    except:
                        raise FilterParsingError
                    files = [ f for f in files if \
                            sign*keys < sign*os.path.getsize(f)/(1020*1024) ]

                elif filter_type in ['runtime', 'year', 'rating']:
                    self.log.info("filtering by %s" % filter_type)

                    if (len(keys)>1):
                        raise FilterParsingError
                    try:
                        keys = list(keys)[0]

                        if keys[0] in ['-','+']:
                            sign = 1 if keys[0] == '+' else -1
                            keys = keys[1:]
                        else:
                            sign = 1

                        keys = float(keys)
                        self.log.info("filtering key: %s%f" % \
                                ( "> " if sign==1 else "< ", keys))
                    except:
                        raise FilterParsingError

                    field = 'm_' + filter_type

                    if filter_type == 'runtime':
                        files = [ f for f in files if \
                                sign*keys <= sign*float(\
                                self.get_runtime(self.cache_imdb[\
                                self.cache_path[f]['imdb_id']][field])) ]
                    else:
                        files = [ f for f in files if \
                                sign*keys <= sign*float(self.cache_imdb[\
                                self.cache_path[f]['imdb_id']][field]) ]


                elif filter_type == 'unsure':
                    self.log.info("filtering unsure movies")
                    files = [ f for f in files if \
                        self.cache_path[f]['g_unsure'] ]

                else:
                    self.log.info("filtering type: %s" %filter_type )
                    self.log.info("filtering keys: %s" % ", ".join(keys))

                    filter_type = 'm_' + filter_type
                    files = filter( lambda m:\
                        set([key.lower() for
                        key in self.imdb_from_path(m)[filter_type]]).\
                                intersection(keys), files)
        except FilterParsingError:
            self.log.error("Invalid filter ! Please read README for syntax")
            files = []

        finally:
            self.log.info("number of files after filtering %d" % len(files))
            return files

    def filter_and_sort_files( self, files):
    # filter the list of files,
    # according to video extensions provided, and user filters

        if self.filter_phrase:
            files = self.user_filter(files)

        if self.order_alpha:
            keyword = 'm_canonical_title'
        else:
            keyword = 'm_rating'

        files.sort( key=lambda f: self.imdb_from_path(f)[keyword],\
                reverse=self.order_reverse)

        return(files)

    def imdb_from_path(self,path):
        try:
            imdb_id = self.cache_path[path]['imdb_id']
            if not imdb_id:
                self.log.error("this path %s was not found on imdb" % path )
                result  = store()
            else:
                result  = self.cache_imdb[imdb_id]
        except:
            self.log.error("this path doesn't belong to cash_path %s" % path )
            result      = store()

        return( result )

    # ********** DISPLAYERS **************************************************
    def show_list(self, files):
        for f in files:
            self.pretty_print(f)


    def pretty_print(self, filename):
    # Print movie with metadata and colors according to arguments

        imdb = self.imdb_from_path(filename)
        info = self.cache_path[filename]
        if not imdb['imdb_id']:
            return(0)

        values_dict = {'b':self.BLUE,
                       'e':self.END,
                       'header':self.RED + '/!\\ ' + self.END if \
                               self.cache_path[filename]['g_unsure'] else '',
                       'title':(self.MAGEN if imdb['imdb_id'] \
                               else self.YELLOW)+to_ascii(imdb['m_title'])+\
                               self.END,
                       'rating':str(imdb['m_rating']),
                       'runtime':self.get_runtime(imdb['m_runtime']),
                       'year':imdb['m_year'],
                       'genre':"%s" % ', '.join(imdb['m_genre']),
                       'filename':os.path.basename(filename) if \
                               os.path.exists(filename) else filename,
                       'director':', '.join(imdb['m_director']),
                       'size': str(int(info['bytesize'] / (1024*1024))) \
                               if info['bytesize'] else None
                      }

        if self.disp_very_long:
            out_str  =u"%(header)s%(title)s (%(b)srating%(e)s: %(rating)s)\n%"
            out_str +="(b)syear%(e)s: %(year)s %(b)sgenre%(e)s: %(genre)s\n%"
            out_str +="(b)sruntime%(e)s: %(runtime)s min\n%"
            out_str +="(b)sfile%(e)s: %(filename)s %(b)ssize%(e)s: %(size)sMo"
            out_str +="\n%(b)sdirector%(e)s: %(director)s\n"
            out_str = out_str % values_dict

            cast_header = self.BLUE+u"cast"+self.END+": "
            len_cast_header = len(cast_header) - len(self.BLUE) - len(self.END)
            out_str+=cast_header
            first = True
            for actor in imdb['m_cast']:
                if first:
                    first = False
                    out_str += actor+'\n'
                else:
                    out_str+=len_cast_header*u' '+actor+'\n'
            out_str += "\n" + self.BLUE + "summary"+self.END+": %s\n---\n" % \
                    imdb['m_summary']
        elif self.disp_long:
            out_str = u"%(header)s%(title)s (%(year)s, %(rating)s, %(runtime)smin) "
            out_str += "[%(b)s%(genre)s%(e)s] from %(director)s: "
            out_str += "%(filename)s\n"
            out_str = out_str % values_dict
        else:
            out_str = u"%(header)s%(title)s (%(year)s) - %(runtime)smin -> %(filename)s\n" % values_dict
        sys.stdout.write(out_str.encode('utf-8'))
        if self.disp_outline and imdb['m_short_summary']:
            sys.stdout.write(unicode( \
                    '*** ' + imdb['m_short_summary']+'\n').encode('utf-8'))

    def html_build(self, files):
    # Show the list of files, using metadata according to arguments

        cell = u"<td width=200 height=250>\
           <a href='%(trailer)s'><img src='%(cover)s' height=150></a><br>\
           <a href=\"%(imdb)s\">%(title)s</a> (%(year)s)<br> \
           <font color=%(color)s>%(genre)s<br>\
           note: %(rating)s, votes: %(votes)s<br>\
           runtime: %(runtime)smin<br>\
           size: %(size)iMo</font><br><br></td>"

        with codecs.open(self.html_fn,'w','utf-8') as out_file:
            out_file.write("<table>\n")
            count = 0
            for f in files:
                info = self.cache_path[f]
                if count % 5 == 0:
                    if count > 0: out_file.write("</tr>")
                    out_file.write("<tr height=200>")

                h = self.imdb_from_path(f)
                if h['imdb_id']:
                    values_dict = {
                        'imdb' :'http://www.imdb.com/title/tt'+h['imdb_id'],
                        'file' : os.path.basename(f)[0:20] if \
                                os.path.exists(f) else '',
                        'size' : round(info['bytesize']/(1024*1024),1) \
                                if os.path.exists(f) else 0,
                        'title': h['m_title'],
                        'color': '#FF3333' if h['g_unsure'] else '#808080',
                        'rating' : str(h['m_rating']) or 'None',
                        'runtime': self.get_runtime(h['m_runtime']),
                        'year':str(h['m_year']),
                        'votes': str(round(h['m_votes']/1000,1))+'K' if \
                                h['m_votes'] else 'None',
                        'cover': h['m_cover'],
                        'genre': ', '.join(h['m_genre']),
                     'trailer':'http://www.youtube.com/results?search_query='+
                                alphanum( h['m_title'],'+')+'+trailer'
                                }
                    # print values_dict
                    finalcell = cell % values_dict
                    out_file.write( finalcell )
                count += 1
            out_file.write("</tr></table>")

    def html_show(self):
        webbrowser.open_new_tab( "file://%s" % self.html_fn )

    def imdb_show(self, files):
        for f in files:
            imdb = self.imdb_from_path(f)
            if imdb['imdb_id']:
                webbrowser.open_new_tab(imdb.imdbURL_movie_main % imdb['imdb_id'])

if __name__ == "__main__":

    consoleLogging( LOG_FORMAT, logging.ERROR )

    options, args  = parse_arguments()

    if options.debug:
        consoleLogging( LOG_FORMAT, logging.INFO)

        rootdir = os.path.expanduser(u"~/.lm")
        filelog = os.path.join( rootdir, u"lm_log.txt" )
        if not os.path.exists( rootdir ):
            os.mkdir( rootdir )
        fileLogging( LOG_FORMAT, logging.INFO, filelog )

        logger.info("argparse namespace: %s" % str(options) )
        logger.info("arg files type: %s" % \
                ', '.join([str(type(f)) for f in args]) )
        logger.info("file system encoding: %s" % sys.getfilesystemencoding())
        logger.info("system encoding: %s" % sys.getdefaultencoding())
        logger.info("locale encoding: %s" % locale.getdefaultlocale()[1])

    else:
        consoleLogging( LOG_FORMAT, logging.ERROR )

    LM  = ListMovies(options, logging.INFO if options.debug \
                else logging.ERROR)

    if options.version:
        print( VERSION )
        sys.exit()

    if options.reset:
        LM.reset_cache_files()
        sys.exit()

    if options.top:
        files = [ "top" + str(i) for i in xrange(250, 0, -1) ]
    elif options.movielist:
            with open(args[0]) as f:
                files = [ s.strip().replace('\n', '') for s in f.readlines() ]
                files = filter(lambda x: len(x) and x[0] != "#", files)
    else:
        files = LM.get_files(args)

    if options.delete_cache:
        LM.delete_cache(files)
        sys.exit()

    if options.top:
        LM.update_caches_with_top( 250 )
    elif options.movielist:
        LM.update_caches_with_paths( files )
    else:
        LM.update_caches_with_paths( files )
        LM.update_cache_imdb_opensubtitles()

    LM.update_cache_imdb_metadata()
    files = LM.filter_and_sort_files(files)

    if options.confirm:
        LM.manual_confirm(files)

    elif options.upload:
        LM.upload_to_opensubtitles(files)

    elif options.download:
        LM.download_subtitle(files, options.download)

    elif options.show or options.html_build:
        LM.html_build(files)
        if options.show:
            LM.html_show()

    elif options.show_imdb:
        LM.imdb_show(files)

    else:
        LM.show_list( files )

