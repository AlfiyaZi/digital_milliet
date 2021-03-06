#!/usr/bin/python

import os, requests, datetime
from uuid import uuid4
import re, sys
from flask import session
from flask.ext.pymongo import PyMongo
from bson.objectid import ObjectId
from bson.json_util import dumps
import json
from MyCapytain.common.reference import URN


class Parser(object):
    """ Parses data for retrieval/storage to/from the database
    """
    def __init__(self,db=None,builder=None,config=None,auth=None):
        """ Parser object

        :param db: Mongo Db Handle
        :type db: PyMongo
        :param builder:  helper for building new Author records
        :type builder: AuthorBuilder
        :param config: configuration dictionary
        :type config: dict
        """

        self.mongo = db
        self.builder = builder
        self.config = config
        self.auth = auth


    def save_from_form(self,vals):
        """Save a new set of annotations from the input form

        :param vals: key/value pairs from input form
        :type vals: dict

        :return: the Milliet number for the saved annotations or None if the record couldn't be saved
        :rtype: string
        """
        data = self.make_annotation(vals)
        raw_id = data['commentary'][0]['hasBody']['@id']
        mil_id = raw_id.split(':').pop()
        rv = None
        m_obj = self.add_to_db(data)
        if m_obj is not None:
            rv = mil_id.split('.')[1]
        return rv

    def edit_save(self,form):
        """Save an edited set of annotations to the db

        :param form: key/value pairs from edit form
        :type form: dict

        :return: True if successful False if not
        :rtype: bool
        """

        modtime = datetime.datetime.utcnow().isoformat()
        record = self.mongo.db.annotation.find_one_or_404({'_id': ObjectId(form['mongo_id'])})
        record['commentary'][0]['hasBody']['chars'] = form['c1text']
        record['bibliography'][0]['hasBody']['chars'] = form['b1text']
        cite_urn = record['commentary'][0]['hasBody']['@id']
        millnum = cite_urn.split('.')[2]


        if 't1_text' in form:
            if form['t1_text'] != '':
                if not record['translation'][0]['hasBody'] is dict:
                    # if we have switched from a uri to text then make sure we have the structure in place
                    record['translation'][0]['hasBody'] = self.build_transl("t1", millnum, form['t1_text'], None, None, form['lang1'])
                else:
                    record['translation'][0]['hasBody']['chars'] = form['t1_text']
                    record['translation'][0]['hasBody']['language'] = form['lang1']
        else:
            record['translation'][0]['hasBody'] = form['t1_uri']

        if 't2_text' in form:
            if form['t2_text'] != '':
                if not record['translation'][1]['hasBody'] is dict:
                    # if we have switched from a uri to text then make sure we have the structure in place
                    record['translation'][1]['hasBody'] = self.build_transl("t2", millnum, form['t2_text'], None, None, form['lang2'])
                else:
                    record['translation'][1]['hasBody']['chars'] = form['t2_text']
                    record['translation'][1]['hasBody']['language'] = form['lang2']
        else:
              record['translation'][1]['hasBody'] = form['t2_uri']

        record['commentary'][0]['modified'] = modtime
        record['bibliography'][0]['modified'] = modtime
        record['translation'][0]['modified'] = modtime
        record['translation'][1]['modified'] = modtime
        if (form['orig_uri'] != ''):
            record['translation'][0]['hasTarget'] = form['orig_uri']
            record['translation'][1]['hasTarget'] = form['orig_uri']
        self.update_contributors(record['commentary'][0])
        self.update_contributors(record['bibliography'][0])
        self.update_contributors(record['translation'][0])
        self.update_contributors(record['translation'][1])

        if (type(record['commentary'][0]['hasTarget']) is not list):
            main_text = dict(
                [("@id", self.make_uri(millnum,'l1')),
                 ("format", "text"),
                 ("chars", ""),
                 ("language", "")
                ])
            record['commentary'][0]['hasTarget'] = ["",main_text]
        record['commentary'][0]['hasTarget'][0] = form['orig_uri']
        record['commentary'][0]['hasTarget'][1]['chars'] = form['orig_text']
        record['commentary'][0]['hasTarget'][1]['language'] = form['orig_lang']

        rv =  None
        if self.validate_annotation(record):
            rv = self.mongo.db.annotation.save(record)
            self.builder.author_db_build(record)
        return rv


    def add_to_db(self,data_dict):
        """Add a new set of annotations ot the database

        :param data_dict: Data dictionary
        :type data_dict: dict

        :return: the inserted db record or None if the record already existed
        :rtype: dict
        """
        cid = data_dict["commentary"][0]["hasBody"]["@id"]
        exists = self.mongo.db.annotation.find_one({"commentary.hasBody.@id" : cid})
        m_obj = None
        if not exists and self.validate_annotation(data_dict):
            m_obj = self.mongo.db.annotation.insert(data_dict)
            #now compile author info
            self.builder.author_db_build(data_dict)
        return m_obj



    def make_annotation(self, vals):
        """Make a structure for the annotation from a set of key/value pairs

        :param vals: key/value pairs from input
        :type values:

        :return: the annotation
        :rtype: dict
        """
        date = datetime.datetime.today()
        milnum = vals['milnum'].zfill(3)
        person = self.make_person()
        primary_source_uri = ""
        if vals['l1uri']:
            primary_source_uri = vals['l1uri']
        elif vals['own_uri_l1']:
            primary_source_uri = vals['own_uri_l1']
        main_text = dict(
            [("@id", self.make_uri(milnum,'l1')),
             ("format", "text"),
             ("chars", vals['l1text']),
             ("language", vals['select_l1'])
            ])

        annotation = dict([
            ("commentary", [dict([
              ("@context", "http://www.w3.org/ns/oa-context-20130208.json"),
              ("@id", self.uid()),
              ("@type", "oa:Annotation"),
              ("annotatedAt", str(date)),
              ("creator",person),
              ("hasBody", dict([
                ("@id", self.make_uri(milnum,'c1')),
                ("format", "text"),
                ("chars", vals['c1text']),
                ("language", "eng")
              ])),
              ("hasTarget", [primary_source_uri,main_text]),
              ("motivatedBy", "oa:commenting")
            ])]),
            ("bibliography", [dict([
              ("@context", "http://www.w3.org/ns/oa-context-20130208.json"),
              ("@id", self.uid()),
              ("@type", "oa:Annotation"),
              ("annotatedAt", str(date)),
              ("creator",person),
              ("hasBody", dict([
                ("@id", self.make_uri(milnum,'b1')),
                ("format", "text"),
                ("chars", vals['b1text']),
                ("language", "eng")
              ])),
              ("hasTarget", self.make_uri(milnum,'c1')),
              ("motivatedBy", "oa:linking")
            ])]),
            ("translation", [dict([
              ("@context", "http://www.w3.org/ns/oa-context-20130208.json"),
              ("@id", self.uid()),
              ("@type", "oa:Annotation"),
              ("annotatedAt", str(date)),
              ("creator",person),
              ("hasBody", self.build_transl("t1", vals['milnum'], vals['t1text'], vals['t1uri'], vals['own_uri_t1'], vals['lang_t1'])),
              ("hasTarget", primary_source_uri),
              ("motivatedBy", "oa:linking")
              ]),
              dict([
              ("@context", "http://www.w3.org/ns/oa-context-20130208.json"),
              ("@id", self.uid()),
              ("@type", "oa:Annotation"),
              ("annotatedAt", str(date)),
              ("creator",person),
              ("hasBody", self.build_transl("t2", vals['milnum'], vals['t2text'], vals['t2uri'], vals['own_uri_t2'], vals['lang_t2'])),
              ("hasTarget", primary_source_uri),
              ("motivatedBy", "oa:linking")
              ])
            ]),
            ("tags", []),
            ("images", [])
        ])
        return annotation



    def uid(self):
        """Create a unique id for an annotation

        :return: uid
        :rtype: string
        """
        uuid = 'digmilann.' + str(uuid4())
        return uuid



    def build_transl(self,num, milnum, text, uri, own_uri, lang):
        """ Build the body of a translation annotation.

        :param num: the translation identifier (t1 or t2)
        :type num: string
        :param milnum: the Milliet number for the annotation
        :type milnum: string
        :param text: the text of the translation (None if uri or own_uri is supplied)
        :type text: String
        :param uri: the uri of a translation - this is expected to be a CTS URN that appears in the linked cts repository
        :type uri: string
        :param own_uri: an user-supplied uri for a translation - this is for an externally linked translation text
        :type own_uri: string
        :param lang: the language code of the translation ('fra' or 'eng')
        :type lang: string

        :return: the body of the translation annotation
        :rtype: string (for a URI) or dict (if an embedded body)
        """
        if not uri and not own_uri:
            body = dict([
              ("@id", self.make_uri(milnum,num)),
              ("format", "text"),
              ("chars", text),
              ("language", lang)
            ])
        elif not uri and own_uri:
            body = own_uri
        else:
            body = uri

        return body



    def get_it(self,millnum):
        """Get the first set of annotations that target the supplied Milliet Number

        :param millnum:  Milliet Number
        :type milnum: string

        :return: the annotation
        :rtype: dict

        :raises 404 Not Found Exception: if the annotation is not found
        """
        obj = self.mongo.db.annotation.find_one_or_404({"commentary.hasBody.@id" : self.make_uri(millnum,'c1')})
        parsed_obj = self.parse_it(obj)
        info = self.mongo.db.annotation.find_one({'works.millnums' : {'$elemMatch':  {'$elemMatch' :{'$in': [millnum]}}}})
        auth_info = {}
        if info is None:
            auth_info['auth'] = ""
            auth_info['work'] = ""
            auth_info['passage'] = ""
        else:
            auth_info['auth'] = info['name']
            for w in info['works']:
                for tup in w['millnums']:
                    if millnum in tup:
                        auth_info['work'] = w['title']
                        auth_info['passage'] = tup[1]

        return parsed_obj, auth_info



    def parse_it(self,obj):
        """ Parse a db record into a dict setup for views

        :param obj: the db record
        :type obj: dict

        :return:  Parsed version of the record
        :rtype: dict
        """
        result = {}
        result['mid'] = obj['_id']
        result['bibl'] = obj['bibliography'][0]['hasBody']['chars']
        result['comm'] = obj['commentary'][0]['hasBody']['chars']
        if 'creator' in obj['commentary'][0]:
            result['creator'] = obj['commentary'][0]['creator']
        else:
            result['creator'] = None
        if 'contributor' in obj['commentary'][0]:
            result['contributor'] = obj['commentary'][0]['contributor']
        else:
            result['contributor'] = None
        tnum = 0
        for transl in obj['translation']:
            tnum = tnum + 1
            if (type(transl['hasBody']) is dict):
                t_num = transl['hasBody']['@id'].split('.')[-1]
                text = transl['hasBody']['chars']
                lang = transl['hasBody']['language']
                result[t_num+'_text'] = text
                result[t_num+'_lang'] = lang
            else:
                t_num = "t" + str(tnum)
                text = transl['hasBody']
                try:
                    urn = URN(text)
                    lang = re.search('\D+', text.split('-')[1]).group(0)
                    result[t_num+'_uri'] = text
                    result[t_num+'_lang'] = lang
                except:
                    # invalid URN we need to recover
                    result[t_num+'_text'] = text
                    result[t_num+'_lang'] = "eng"
                    pass
        if (type(obj['commentary'][0]['hasTarget']) is list):
            result['orig_uri'] = obj['commentary'][0]['hasTarget'][0]
            result['orig_text'] = obj['commentary'][0]['hasTarget'][1]['chars']
        elif (type(obj['commentary'][0]['hasTarget']) is dict):
            result['orig_uri'] = ""
            result['orig_text'] = obj['commentary'][0]['hasTarget']['chars']
        else:
            result['orig_uri'] = obj['commentary'][0]['hasTarget']

        return result

    def validate_annotation(self,annotation):
        """Validate the structure of an annotation.

        This is not foolproof but it attempts to catch some errors that could come in from mistakes
        in data entry. It would be good to make sure these all couldn't occur to begin with.

        :param annotation: the annotation record
        :type annotation: dict

        :return: True if valid False if not
        :rtype: bool
        """
        try:
            if (annotation['commentary'][0]['hasTarget'][0] != ''):
                urn = URN(annotation['commentary'][0]['hasTarget'][0])
        except ValueError as err:
            raise ValueError("Invalid commentary target - not parseable as URN")
        try:
            if isinstance(annotation['translation'][0]['hasBody'],str):
                urn = URN(annotation['translation'][0]['hasBody'])
        except ValueError as err:
            raise ValueError("Invalid translation 1 uri - not parseable as URN")
        try:
            if isinstance(annotation['translation'][1]['hasBody'],str):
                urn = URN(annotation['translation'][1]['hasBody'])
        except ValueError as err:
            raise ValueError("Invalid translation 2 uri - not parseable as URN")
        return True


    def process_comm(self,comm_list):
        """ Extract a sorted list of milliet numbers from a set of commentary annotations

        :param comm_list: set of commentary annotations
        :type comm_list: list

        :return: sorted list of extracted Milliet numbers
        :rtype: list
        """
        millnum_list = []
        convert = lambda text: int(text) if text.isdigit() else text
        alphanum_key = lambda key: [ convert(re.split('([A-Za-z]+)', key)[0]) ]
        for row in comm_list:
            try:
                cite_urn = str(row['commentary'][0]['hasBody']['@id'])
                millnum = cite_urn.split('.')[2]
                if millnum:
                    millnum_list.append(millnum)
                else:
                    pass
            except:
                pass
        return sorted(millnum_list,key=alphanum_key)

    def make_uri(self, milnum, subcoll):
        """ Make a Cite Collection URI for an annotation

        N.B. this is not a valid implementation of the CITE protocol, as it does not support
        CITE collections.  Future implementations should consider replacing this with a different identifier syntax.

        :param: milnum: The Milliet number
        :type: milnum: string

        :param: subcoll: the subcollection identifier (e.g. commentary, bibliography, etc.)
        :type: string

        :return:  the compiled URI
        :rtype: string
        """
        return self.config['CITE_URI_PREFIX'] +  self.config['CITE_COLLECTION'] + '.' + milnum + '.' + subcoll

    def make_person(self):
        """ Make a Person for an annotation (i.e for contributor or creator)
        Uses the URI identifier for the user of the currently authenticated session

        :return: Person properties suitable for inclusion in the annotation
        :rtype: dict
        """
        person = self.auth.current_user()
        if person:
            return dict([
                ("id", person['uri']),
                ("type", "Person"),
                ("name", person['name'])
            ])
        else:
            return None

    def update_contributors(self,annotation_dict=dict):
        """ Update the contributors for an annotation

        Inserts a Person object for the currently authenticated user if she doesn't already appear
        as either creator or contributor.

        :param annotation_dict: the annotation to update
        :type annotation_dict: dict

        """
        contributors = annotation_dict.setdefault('contributor',[])
        person = self.make_person()
        if person:
            found = False
            for c in contributors:
                if c['id'] == person['id'] :
                    found = True
                    break
            if not found:
                if 'creator' not in annotation_dict or annotation_dict['creator']['id'] != person['id']:
                    contributors.append(person)
