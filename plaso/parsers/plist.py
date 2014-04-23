#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright 2013 The Plaso Project Authors.
# Please see the AUTHORS file for details on individual authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""This file contains the Property List (Plist) Parser.

Plaso's engine calls PlistParser when it encounters Plist files to be processed.
"""

import binascii
import logging

from binplist import binplist

# Need to import plist to ensure plugins are registered.
# pylint: disable=unused-import
from plaso.parsers import plist_plugins

from plaso.lib import errors
from plaso.lib import parser
from plaso.lib import plugin
from plaso.lib import utils
from plaso.parsers.plist_plugins import interface


class PlistParser(parser.BaseParser):
  """De-serializes and parses plists the event objects are generated by plist.

  The Plaso engine calls parsers by their Parse() method. This parser's
  Parse() has GetTopLevel() which deserializes plist files using the binplist
  library and calls plugins (PlistPlugin) registered through the
  interface by their Process() to yield EventObject objects back
  to the engine.

  Plugins are how this parser understands the content inside a plist file,
  each plugin holds logic specific to a particular plist file. See the
  interface and plist_plugins/ directory for examples of how plist plugins are
  implemented.
  """

  NAME = 'plist'

  def __init__(self, pre_obj, config):
    """Initializes the parser.

    Args:
      pre_obj: pre-parsing object.
      config: configuration object.
    """
    super(PlistParser, self).__init__(pre_obj, config)
    plugin_filter_string = getattr(self._config, 'parsers', None)
    self._plugins = plugin.GetRegisteredPlugins(
        interface.PlistPlugin, pre_obj, plugin_filter_string)

  def GetTopLevel(self, file_object, file_name=''):
    """Returns the deserialized content of a plist as a dictionary object.

    Args:
      file_object: A file-like object to parse.
      file_name: The name of the file-like object.

    Returns:
      A dictionary object representing the contents of the plist.
    """
    try:
      top_level_object = binplist.readPlist(file_object)
    except binplist.FormatError as exception:
      raise errors.UnableToParseFile(
          u'[PLIST] File is not a plist file: {0:s}'.format(
              utils.GetUnicodeString(exception)))
    except (
        LookupError, binascii.Error, ValueError, AttributeError) as exception:
      raise errors.UnableToParseFile(
          u'[PLIST] Unable to parse XML file, reason: {0:s}'.format(
              exception))
    except OverflowError as exception:
      raise errors.UnableToParseFile(
          u'[PLIST] Unable to parse: {0:s} with error: {1:s}'.format(
              file_name, exception))

    if not top_level_object:
      raise errors.UnableToParseFile(
          u'[PLIST] File is not a plist: {0:s}'.format(
              utils.GetUnicodeString(file_name)))

    # Since we are using readPlist from binplist now instead of manually
    # opening up the BinarPlist file we loose this option. Keep it commented
    # out for now but this needs to be tested a bit more.
    # TODO: Re-evaluate if we can delete this or still require it.
    #if bpl.is_corrupt:
    #  logging.warning(
    #      u'[PLIST] corruption detected in binary plist: {0:s}'.format(
    #          file_name))

    return top_level_object

  def Parse(self, file_entry):
    """Parse and extract values from a plist file.

    Args:
      file_entry: the file entry object.

    Yields:
      A plist event object (instance of event.PlistEvent).
    """
    # TODO: Should we rather query the stats object to get the size here?
    file_object = file_entry.GetFileObject()
    file_size = file_object.get_size()

    if file_size <= 0:
      file_object.close()
      raise errors.UnableToParseFile(
          u'[PLIST] file size: {0:d} bytes is less equal 0.'.format(file_size))

    # 50MB is 10x larger than any plist seen to date.
    if file_size > 50000000:
      file_object.close()
      raise errors.UnableToParseFile(
          u'[PLIST] file size: {0:d} bytes is larger than 50 MB.'.format(
              file_size))

    top_level_object = None
    try:
      top_level_object = self.GetTopLevel(file_object, file_entry.name)
    except errors.UnableToParseFile:
      file_object.close()
      raise

    if not top_level_object:
      file_object.close()
      raise errors.UnableToParseFile(
          u'[PLIST] unable to parse: {0:s} skipping.'.format(file_entry.name))

    file_system = file_entry.GetFileSystem()
    plist_name = file_system.BasenamePath(file_entry.name)

    for plist_plugin in self._plugins.itervalues():
      try:
        for event_object in plist_plugin.Process(plist_name, top_level_object):
          event_object.plugin = plist_plugin.plugin_name
          yield event_object
      except errors.WrongPlistPlugin as exception:
        logging.debug(u'[PLIST] Wrong plugin: {0:s} for: {1:s}'.format(
            exception[0], exception[1]))

    file_object.close()
