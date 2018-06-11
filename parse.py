# -*- coding: utf-8 -*-

# A simple RTF parser based loosely on the 1.9.1 standard. This is intended
# primarily to extract formatted text, but could easily be extended and turned
# into a general parser in the future.

import re, time, binascii
from enum import Enum

class RTFParser(object):

	# Token types
	class TokenType(Enum):
		OPEN_BRACE        = 1
		CLOSE_BRACE       = 2
		CONTROL_WORDORSYM = 3
		CHARACTER         = 4
		EOF               = 5

	# Text formatting attributes and their default values. Values with booleans
	# should be set to either True (for on) or False (for off.) If an attribute
	# doesn't exist in the current state, it means we must retrieve its value
	# from the first state up the stack where it's defined.
	__stateFormattingAttributes = {
		'italic':        False,
		'bold':          False,
		'underline':     False,
		'strikethrough': False,
		'alignment':     'left'
	}

	__specialStateVars = [
		'groupSkip',      # we're skipping the current group
		'inField',        # we're inside a {\field} group
		'inFieldinst',    # we're inside the {\fldinst} portion of a \field
		'inFieldrslt',    # we're inside the {\fldrslt} portion of a \field
		'inPict',         # We're currently parsing an embedded image
		'pictAttributes', # Attributes assigned to the image we're currently parsing
		'inBlipUID',      # We're parsing an image's unique ID
		'blipUID'         # Contains an image's unique ID
	]

	###########################################################################

	# Read-only public access to the full state.
	@property
	def fullState(self):

		return self.__fullStateCache

	###########################################################################

	# Content
	def __init__(self, options):

		self.reset()

		# This class only parses the RTF. How that data is encoded and represented
		# after parsing is up to the client, and the client should provide a
		# at least a minimum number of callbacks to process that data as it's
		# extracted from the RTF.
		if not options or 'callbacks' not in options:
			raise Exception('Did not pass required callbacks.')
		elif (
			'onOpenParagraph'   not in options['callbacks'] or
			'onAppendParagraph' not in options['callbacks'] or
			'onStateChange'     not in options['callbacks'] or
			'onField'           not in options['callbacks']
		):
			raise Exception('Did not pass required callbacks.')

		self.__options = options

	###########################################################################

	# Get the control word or symbol at the current position
	def __getControlWordOrSymbol(self):

		token = '\\'

		if not self.__content[self.__curPos].isalpha() and not self.__content[self.__curPos].isspace():

			# Character represented in \'xx form (if no hexadecimal digit
			# follows, it will be the responsibility of the parser to treat it
			# as an unsupported control symbol.)
			if "'" == self.__content[self.__curPos]:
				token = token + self.__content[self.__curPos]
				self.__curPos = self.__curPos + 1
				decimalCount = 0
				while decimalCount < 2 and (
					self.__content[self.__curPos].isdigit() or
					self.__content[self.__curPos].upper() in ['A', 'B', 'C', 'D', 'E']
				):
					token = token + self.__content[self.__curPos]
					self.__curPos = self.__curPos + 1
					decimalCount += 1

			# Control symbol
			else:
				token = token + self.__content[self.__curPos]
				self.__curPos = self.__curPos + 1

		# Control word
		elif self.__content[self.__curPos].isalpha():

			while self.__content[self.__curPos].isalpha():
				token = token + self.__content[self.__curPos]
				self.__curPos = self.__curPos + 1

			# Control word has a numeric parameter
			digitIndex = self.__curPos
			if self.__content[self.__curPos].isdigit() or '-' == self.__content[self.__curPos]:
				while self.__content[self.__curPos].isdigit() or (self.__curPos == digitIndex and '-' == self.__content[self.__curPos]):
					token = token + self.__content[self.__curPos]
					self.__curPos = self.__curPos + 1

			# If there's a single space that serves as a delimiter, the spec says
			# we should append it to the control word.
			if self.__content[self.__curPos].isspace():
				token = token + self.__content[self.__curPos]
				self.__curPos = self.__curPos + 1

		else:
			raise ValueError("Encountered unescaped '\\'")

		return token

	###########################################################################

	# Get next token from the currently loaded RTF
	def __getNextToken(self):

		# We haven't opened an RTF yet
		if not self.__content:
			return False

		# We've reached the end of the file
		elif self.__curPos >= len(self.__content):
			return [self.TokenType.EOF, '']

		# Control words and their parameters count as single tokens
		elif '\\' == self.__content[self.__curPos]:
			self.__curPos = self.__curPos + 1
			return [self.TokenType.CONTROL_WORDORSYM, self.__getControlWordOrSymbol()]

		# Covers '{', '}' and any other character
		else:

			tokenType = self.TokenType.CHARACTER

			if '{' == self.__content[self.__curPos]:
				tokenType = self.TokenType.OPEN_BRACE
			elif '}' == self.__content[self.__curPos]:
				tokenType = self.TokenType.CLOSE_BRACE

			self.__curPos = self.__curPos + 1
			return [tokenType, self.__content[self.__curPos - 1]]

	###########################################################################

	# Opens a new paragraph.
	def __openParagraph(self):

		self.__options['callbacks']['onOpenParagraph'](self)

	###########################################################################

	# Appends the specified string to the current paragraph.
	def __appendToCurrentParagraph(self, string):

		self.__options['callbacks']['onAppendParagraph'](self, string)

	###########################################################################

	# Closes the current paragraph.
	def __closeParagraph(self):

		if 'onCloseParagraph' in self.__options['callbacks']:
			self.__options['callbacks']['onCloseParagraph'](self)

	###########################################################################

	# Reset the current state's formatting attributes to their default values.
	def __resetStateFormattingAttributes(self, doCallback = True):

		formerState = self.__fullStateCache

		for attribute in self.__stateFormattingAttributes.keys():
			self.__curState[attribute] = self.__stateFormattingAttributes[attribute]

		# Update the full state cache now that the attributes have changed
		self.__cacheFullState()

		if doCallback and 'onStateChange' in self.__options['callbacks']:
			self.__options['callbacks']['onStateChange'](self, formerState, self.__fullStateCache)

	###########################################################################

	# Sets a state value. Styling attributes (bold, italic, etc.) should trigger
	# the onStateChange event. Boolean styling values like italic, bold, etc.
	# should be set to True or False. Not doing so will result in undefined
	# behavior. State values that are used internally and that don't effect the
	# output can be set to whatever you want and should not trigger onStateChange.
	def __setStateValue(self, attribute, value, triggerOnStateChange = True):

		oldState = self.__fullStateCache
		self.__curState[attribute] = value

		# Update the full state cache now that the attribute has changed
		self.__cacheFullState()

		if triggerOnStateChange and 'onStateChange' in self.__options['callbacks']:
			self.__options['callbacks']['onStateChange'](self, oldState, self.__fullStateCache)

	###########################################################################

	# Sets a document level attribute (not the same as a formatting attribute.)
	# Examples are the value of \*\generator, etc. This means nothing to the
	# parser itself, and will do nothing unless a callback has been registered
	# to handle it.
	def __setDocumentAttribute(self, attribute, value):

		if 'onSetDocumentAttribute' in self.__options['callbacks']:
			self.__options['callbacks']['onSetDocumentAttribute'](self, attribute, value)

	###########################################################################

	# Process a \field group.
	def __parseField(self, fldinst, fldrslt):

		# We let the callback handle it
		if 'onField' in self.__options['callbacks']:
			self.__options['callbacks']['onField'](self, fldinst, fldrslt)

		# There's no callback that knows how to handle it, so we'll just do things
		# the dumb way by appending the \fldrslt value to the current paragraph.
		else:
			self.__appendToCurrentParagraph(fldrslt)

	###########################################################################

	# Parse the \*\generator attribute
	def __parseGenerator(self):

		# TODO
		pass

	###########################################################################

	# Parses an embedded image. For now, this only supports the default hex dump
	# format.
	def __parseImage(self, attributes, pict):

		if 'onImage' in self.__options['callbacks']:
			self.__options['callbacks']['onImage'](self, attributes, binascii.unhexlify(pict))

	###########################################################################

	# Parses a hexadecimal Image ID contained in a bliptag destination. This
	# value should be identical to whatever's specified in \blipuid.
	def __parseImageID(self, hexval):

		self.__setStateValue('blipUID', int(hexval.lstrip('0'), 16), False)

	###########################################################################

	# Executes a control word or symbol
	def __executeControl(self, word, param):

		# If we're parsing a \fldinst value and encounter another control word
		# with the \* prefix, we know we're done parsing the parts of \fldinst
		# we care about (this will change as I handle more of the RTF spec.)
		if '\\*' == word and 'inFieldinst' in self.__curState and self.__curState['inFieldinst']:
			self.__setStateValue('inFieldinst', False, False)

		################################################
		#       Part 1. Destinations and fields        #
		################################################

		# We'll treat the value of \*\generator as a document attribute.
		if '\*' == self.__prevToken[1] and word == '\\generator':
			# TODO
			#self.__parseGenerator()
			self.__setStateValue('groupSkip', True, False)

		# Proprietary to LibreOffice / OpenOffice, and I can't even find
		# documentation for what it's supposed to do, so just skip over it.
		elif '\*' == self.__prevToken[1] and word == '\\pgdsctbl':
			self.__setStateValue('groupSkip', True, False)

		# Skip over these sections. We're not going to use them (at least
		# for now.)
		elif self.TokenType.OPEN_BRACE == self.__prevToken[0] and (
			word == '\\fonttbl' or
			word == '\\filetbl' or
			word == '\\colortbl' or
			word == '\\stylesheet'or
			word == '\\stylerestrictions' or
			word == '\\listtables' or
			word == '\\revtbl' or
			word == '\\rsidtable' or
			word == '\\mathprops' or
			word == '\\generator' or
			word == '\\info' # TODO: parse this into document attributes
		):
			self.__setStateValue('groupSkip', True, False)

		# Beginning of a field
		elif self.TokenType.OPEN_BRACE == self.__prevToken[0] and '\\field' == word:
			self.__setStateValue('inField', True, False)

		# Most recent calculated result of field. In practice, this is also
		# the text that would be parsed into the paragraph by an RTF reader
		# that doesn't understand fields.
		elif self.TokenType.OPEN_BRACE == self.__prevToken[0] and '\\fldrslt' == word:
			self.__setStateValue('inFieldrslt', True, False)

		# Field instruction
		elif '\\*' == self.__prevToken[1] and '\\fldinst' == word:
			self.__setStateValue('inFieldinst', True, False)

		################################################
		#           Part 2. Embedded Images            #
		################################################

		# We've entered an embedded image.
		elif self.TokenType.OPEN_BRACE == self.__prevToken[0] and '\\pict' == word:
			self.__setStateValue('inPict', True, False)
			self.__setStateValue('pictAttributes', {}, False)

		# We'll encounter this destination when parsing images. It's a way to
		# uniquely identify the image. In my experience with test data, blipuid
		# and bliptagN are different representations of the same value.
		elif '\\*' == self.__prevToken[1] and '\\blipuid' == word:

			# We already got the ID in a simpler way, so we can skip over this destination
			if 'blipUID' in self.__curState:
				self.__setStateValue('groupSkip', True, False)

			# We haven't gotten the ID yet, so go ahead and parse this destination
			else:
				self.__setStateValue('inBlipUID', True, False)

		# This is the other (easier) way to uniquely identify an image
		elif '\\bliptag' == word:
			self.__setStateValue('blipUID', int(param, 10), False)

		# Various image formatting parameters and metadata
		elif 'pictAttributes' in self.__curState and word in [
			'\\picscalex',    # Horizontal scaling %
			'\\picscaley',    # Vertical scaling %
			'\\piccropl',     # Twips (1/1440 of an inch) to crop off the left
			'\\piccropr',     # Twips (1/1440 of an inch) to crop off the right
			'\\piccropt',     # Twips (1/1440 of an inch) to crop off the top
			'\\piccropb',     # Twips (1/1440 of an inch) to crop off the bottom
			'\\picw',         # Width in pixels (if image is bitmap or from QuickDraw)
			'\\pich',         # Height in pixels (if image is bitmap or from QuickDraw)
			'\\picwgoal',     # Desired width in twips (1/1440 of an inch)
			'\\pichgoal',     # Desired height in twips (1/1440 of an inch)
			'\\picbpp',       # Specifies the bits per pixel in a metafile bitmap.
			                  # The valid range is 1 through 32, with 1, 4, 8, and
			                  # 24 being recognized.

			# These apply only to Windows bitmap images
			'\\wbmbitspixel', # From the 1.9.1 spec: "Number of adjacent color bits
			                  # on each plane needed to define a pixel. Possible
			                  # values are 1 (monochrome), 4 (16 colors), 8
			                  # (256 colors) and 24 (RGB). The default value is 1."
			'\\wbmplanes',    # From the 1.9.1 spec: "Number of bitmap color planes
			                  # (must equal 1)."
			'\\wbmwidthbytes' # From the 1.9.1 spec: "Specifies the number of bytes
			                  # in each raster line. This value must be an even
			                  # number because the Windows Graphics Device Interface
			                  # (GDI) assumes that the bit values of a bitmap form
			                  # an array of integer (two-byte) values. In other
			                  # words, \wbmwidthbytes multiplied by 8 must be the
			                  # next multiple of 16 greater than or equal to the
			                  # \picw (bitmap width in pixels) value.
		]:
			pictAttributes = self.__curState['pictAttributes']
			pictAttributes[word] = int(param, 10)
			self.__setStateValue('pictAttributes', pictAttributes, False)

		# JPG
		elif 'pictAttributes' in self.__curState and '\\jpegblip' == word:
			pictAttributes = self.__curState['pictAttributes']
			pictAttributes['source'] = 'jpeg'
			self.__setStateValue('pictAttributes', pictAttributes, False)

		# PNG
		elif 'pictAttributes' in self.__curState and '\\pngblip' == word:
			pictAttributes = self.__curState['pictAttributes']
			pictAttributes['source'] = 'png'
			self.__setStateValue('pictAttributes', pictAttributes, False)

		# EMF (Enhanced metafile)
		elif 'pictAttributes' in self.__curState and '\\emfblip' == word:
			pictAttributes = self.__curState['pictAttributes']
			pictAttributes['source'] = 'emf'
			self.__setStateValue('pictAttributes', pictAttributes, False)

		# OS/2 metafile
		elif 'pictAttributes' in self.__curState and '\\pmmetafile' == word:
			pictAttributes = self.__curState['pictAttributes']
			pictAttributes['source'] = 'os2meta'
			pictAttributes['metafileType'] = param
			self.__setStateValue('pictAttributes', pictAttributes, False)

		# Windows metafile
		elif 'pictAttributes' in self.__curState and '\\wmetafile' == word:
			pictAttributes = self.__curState['pictAttributes']
			pictAttributes['source'] = 'winmeta'
			pictAttributes['metafileMappingMode'] = param
			self.__setStateValue('pictAttributes', pictAttributes, False)

		# Windows device-independent bitmap
		elif 'pictAttributes' in self.__curState and '\\dibitmap' == word:
			pictAttributes = self.__curState['pictAttributes']
			pictAttributes['source'] = 'wdibmp'
			pictAttributes['bitmapType'] = param
			self.__setStateValue('pictAttributes', pictAttributes, False)

		# Windows device-dependent bitmap
		elif 'pictAttributes' in self.__curState and '\\wbitmap' == word:
			pictAttributes = self.__curState['pictAttributes']
			pictAttributes['source'] = 'wddbmp'
			pictAttributes['bitmapType'] = param
			self.__setStateValue('pictAttributes', pictAttributes, False)

		################################################
		#      Part 3. Escaped special characters      #
		################################################

		elif '\\\\' == word:
			self.__appendToCurrentParagraph('\\')

		elif '\\{' == word:
			self.__appendToCurrentParagraph('{')

		elif '\\}' == word:
			self.__appendToCurrentParagraph('}')

		################################################
		# Part 4. Unicode and other special Characters #
		################################################

		# Non-breaking space
		elif '\\~' == word:
			self.__appendToCurrentParagraph('\N{NO-BREAK SPACE}')

		# Non-breaking hyphen
		elif '\\_' == word:
			self.__appendToCurrentParagraph('\N{NON-BREAKING HYPHEN}')

		# A space character with the width of the letter 'm' in the current font
		elif '\\emspace' == word:
			self.__appendToCurrentParagraph('\N{EM SPACE}')

		# A space character with the width of the letter 'n' in the current font
		elif '\\enspace' == word:
			self.__appendToCurrentParagraph('\N{EN SPACE}')

		# En dash
		elif '\\endash' == word:
			self.__appendToCurrentParagraph('\N{EN DASH}')

		# Em dash
		elif '\\emdash' == word:
			self.__appendToCurrentParagraph('\N{EM DASH}')

		# Left single quote
		elif '\\lquote' == word:
			self.__appendToCurrentParagraph('\N{LEFT SINGLE QUOTATION MARK}')

		# Right single quote
		elif '\\rquote' == word:
			self.__appendToCurrentParagraph('\N{RIGHT SINGLE QUOTATION MARK}')

		# Left double quote
		elif '\\ldblquote' == word:
			self.__appendToCurrentParagraph('\N{LEFT DOUBLE QUOTATION MARK}')

		# Right double quote
		elif '\\rdblquote' == word:
			self.__appendToCurrentParagraph('\N{RIGHT DOUBLE QUOTATION MARK}')

		# Non-paragraph-breaking line break
		elif '\\line' == word:
			self.__appendToCurrentParagraph('\n')

		# Tab character
		elif '\\tab' == word:
			self.__appendToCurrentParagraph('\t')

		# tab
		elif '\\bullet' == word:
			self.__appendToCurrentParagraph('\N{BULLET}')

		# Current date (long form)
		elif '\\chdate' == word or '\\chdpl' == word:
			self.__appendToCurrentParagraph(time.strftime("%A, %B %d, %Y"))

		# Current date (abbreviated form)
		elif '\\chdpa' == word:
			self.__appendToCurrentParagraph(time.strftime("%m/%d/%Y"))

		# Current date (abbreviated form)
		elif '\\chtime' == word:
			self.__appendToCurrentParagraph(time.strftime("%I:%M:%S %p"))

		# A character of the form \uXXX to be added to the current paragraph.
		# Unlike \'XX, \u takes a decimal number instead of hex.
		elif '\\u' == word and param:
			try:
				self.__appendToCurrentParagraph(chr(int(param, 10)))
			except ValueError:
				return

		# A character of the form \'XX to be added to the current paragraph
		elif "\\'" == word and param:

			try:

				charCode = int(param, 16)
				prevTokenParts = self.__splitControlWord(self.__prevToken)

				# Per the RTF standard, if a \uXXX unicode symbol has an ANSI
				# equivalent, the ANSI character will be encoded directly
				# following \uXXX in the form \'XX. This is for backward
				# compatibility with older RTF readers. Whenever we encounter
				# \'XX directly after \uXXX, therefore, we'll ignore it. Also,
				# \'XX can only have a maximum value of 255 (FF.) Since my
				# tokenizer doesn't detect this and might pick up extra digits,
				# we do a bounds check here and ignore the character if it falls
				# out of bounds.
				if '\\u' != prevTokenParts[0] and charCode <= 255:
					self.__appendToCurrentParagraph(chr(charCode))

			except ValueError:
				return

		################################################
		#    Part 5. Misc control words and symbols    #
		################################################

		# We're ending the current paragraph and starting a new one
		elif '\\par' == word:
			self.__closeParagraph()
			self.__openParagraph()

		# Reset all styling to an off position in the current state
		elif '\\plain' == word:
			self.__resetStateFormattingAttributes()

		# Paragraph alignment
		elif '\\ql' == word:
			self.__setStateValue('alignment', 'left')

		elif '\\qr' == word:
			self.__setStateValue('alignment', 'right')

		elif '\\qc' == word:
			self.__setStateValue('alignment', 'center')

		elif '\\qd' == word:
			self.__setStateValue('alignment', 'distributed')

		elif '\\qj' == word:
			self.__setStateValue('alignment', 'justified')

		elif '\\qt' == word:
			self.__setStateValue('alignment', 'thai-distributed')

		# TODO: how do I want to handle \qkN alignment? Will require setting
		# two attributes.

		# Italic
		elif '\\i' == word:
			if param is None or '1' == param:
				self.__setStateValue('italic', True)
			else:
				self.__setStateValue('italic', False)

		# Bold
		elif '\\b' == word:
			if param is None or '1' == param:
				self.__setStateValue('bold', True)
			else:
				self.__setStateValue('bold', False)

		# Underline
		elif '\\ul' == word:
			if param is None or '1' == param:
				self.__setStateValue('underline', True)
			else:
				self.__setStateValue('underline', False)

		# Strike-through
		elif '\\strike' == word:
			if param is None or '1' == param:
				self.__setStateValue('strikethrough', True)
			else:
				self.__setStateValue('strikethrough', False)

	###########################################################################

	# Splits a control word token into its word and parameter parts. Returns an
	# array of the form [word, parameter]. If there's no parameter, that part of
	# the array will be set to None.
	def __splitControlWord(self, token):

		control = token[1].strip()

		paramSearch = re.search('-?\d+', control)
		if paramSearch:
			paramStartIndex = paramSearch.start()
			word = control[0:paramStartIndex]
			param = control[paramStartIndex:]
		else:
			word = control
			param = None

		return [word, param]

	###########################################################################

	# Reset to a default state where all the formatting attributes are turned off.
	def __initState(self):

		self.__curState = {}
		self.__resetStateFormattingAttributes(False)
		self.__curState['groupSkip'] = False
		self.__curState['inField'] = False

		self.__fullStateCache = self.__curState.copy()

	###########################################################################

	# Crawls up the state stack to fill in any attributes in the current state
	# that are inherited from a previous state, then caches the result in
	# self.__fullStateCache.
	def __cacheFullState(self):

		state = self.__curState.copy()

		for attribute in self.__stateFormattingAttributes.keys():
			if attribute not in state:
				for i in reversed(range(len(self.__stateStack))):
					if attribute in self.__stateStack[i]:
						state[attribute] = self.__stateStack[i][attribute]
						break

		# Special non-attribute state variables
		for stateVar in self.__specialStateVars:
			if stateVar not in state:
				for i in reversed(range(len(self.__stateStack))):
					if stateVar in self.__stateStack[i]:
						state[stateVar] = self.__stateStack[i][stateVar]
						break

		self.__fullStateCache = state
		return state

	###########################################################################

	# Resets the parser to an initialized state so we can parse another document.
	def reset(self):

		# A string containing the content of an RTF file
		self.__content = False

		# Our current index into self.__content
		self.__curPos = 0

		# Formatting states at various levels of curly braces
		self.__stateStack = []

		# Values that were set in the current formatting state. To see the full
		# state, view the contents of self.__fullStateCache (make sure to call 
		# self.__cacheFullState() whenever the state changes.)
		self.__curState = False

		# Walking through the state stack to construct a full representation of
		# the current state is expensive. Therefore, we should only do so once
		# whenever the state actually changes, then cache the result as long as
		# the state stays the same so we can refer back to it frequently without
		# slowing things down. I discovered the need for this after profiling.
		self.__fullStateCache = False

		# Stores the current token during parsing
		self.__curToken = False

		# Records the previously retrieved token during parsing
		self.__prevToken = False

	###########################################################################

	# Returns true if the specified attribute is a formatting attribute and false
	# if not.
	def isAttributeFormat(self, attr):

		if attr in self.__stateFormattingAttributes:
			return True
		else:
			return False

	###########################################################################

	# Parse an RTF file.
	def openFile(self, filename):

		self.reset()
		rtfFile = open(filename, 'r')
		self.__content = rtfFile.read()
		rtfFile.close()

	###########################################################################

	# Parse an RTF from an already loaded string.
	def openString(self, rtfContent):

		self.reset()
		self.__content = rtfContent

	###########################################################################

	# Parse the RTF and return an array of formatted paragraphs.
	def parse(self):

		if self.__content:

			# Used as a temporary buffer for data inside a \field group
			fldInst = ''
			fldRslt = ''

			# A temporary buffer for data inside a blipuid destination (for
			# identifying embedded images)
			blipUID = ''

			# A temporary buffer of picture data. For now, we're only supporting
			# the default hex dump format. TODO: support binary format (but does
			# any RTF writer actually output this...?)
			pict = ''

			self.__curToken = self.__getNextToken()
			self.__prevToken = False

			# Start with a default state where all the formatting attributes are
			# turned off.
			self.__initState()

			# Open our initial paragraph
			self.__openParagraph()

			while self.TokenType.EOF != self.__curToken[0]:

				# Push the current state onto the stack and create a new local copy.
				if self.TokenType.OPEN_BRACE == self.__curToken[0]:
					self.__stateStack.append(self.__curState)
					self.__curState = {}

				# Restore the previous state.
				elif self.TokenType.CLOSE_BRACE == self.__curToken[0]:

					oldStateCopy = self.__curState.copy()
					oldStateFull = self.__fullStateCache # used in call to onStateChange
					self.__curState = self.__stateStack.pop()
					self.__cacheFullState() # Update the full state cache

					# If we're not skipping over a group or processing a field, call
					# the onCloseGroup hook.
					if (
						'groupSkip' not in oldStateCopy or
						not oldStateCopy['groupSkip']
					) and (
						'inField' not in oldStateCopy or
						not oldStateCopy['inField']
					) and (
						'inBlipUID' not in oldStateCopy or
						not oldStateCopy['inBlipUID']
					) and (
						'inPict' not in oldStateCopy or
						not oldStateCopy['inPict']
					) and 'onStateChange' in self.__options['callbacks']:
						self.__options['callbacks']['onStateChange'](self, oldStateFull, self.__fullStateCache)

					# We just exited a \field group. Process it and then reset the
					# \field data buffer.
					if 'inField' in oldStateCopy and oldStateCopy['inField']:
						self.__parseField(fldInst, fldRslt)
						fldInst = ''
						fldRslt = ''

					# We're parsing an image ID (other possible source of ID is
					# the bliptag control word.)
					if 'inBlipUID' in oldStateCopy and oldStateCopy['inBlipUID']:
						self.__parseImageID(blipUID)
						blipUID = ''

					# We're parsing an embedded image.
					if 'inPict' in oldStateCopy and oldStateCopy['inPict']:
						self.__parseImage(oldStateCopy['pictAttributes'], pict)
						pict = ''

				# We could be skipping over something we're not going to use, such
				# as \fonttbl, \stylesheet, etc.
				elif not self.__fullStateCache['groupSkip']:

					# We're inside the fldrslt portion of a field. Test for this
					# and fieldinst before processing control words, because if
					# there are control words in the field, we're just going to
					# copy everything verbatim into the string and let the client
					# worry about passing it back to another instance of the
					# parser for processing. Hacky? Maybe. But it works.
					if 'inFieldrslt' in self.__fullStateCache and self.__fullStateCache['inFieldrslt']:
						fldRslt += self.__curToken[1]

					# We're inside the \fldinst portion of a field.
					elif 'inFieldinst' in self.__fullStateCache and self.__fullStateCache['inFieldinst']:
						fldInst += self.__curToken[1]

					# We're parsing a \blipuid value to identify an image
					elif 'inBlipUID' in self.__fullStateCache and self.__fullStateCache['inBlipUID']:
						blipUID += self.__curToken[1]

					# We're executing a control word. Execute this before
					# appending tokens to any special destination or group that
					# might contain control words.
					elif self.TokenType.CONTROL_WORDORSYM == self.__curToken[0]:
						tokenParts = self.__splitControlWord(self.__curToken)
						self.__executeControl(tokenParts[0], tokenParts[1])

					# We're parsing a \pict group, which represents an embedded image
					elif 'inPict' in self.__fullStateCache and self.__fullStateCache['inPict'] and not self.__curToken[1].isspace():
						pict += self.__curToken[1]

					# Just an ordinary printable character (note that literal
					# newlines are ignored. Only \line will result in an inserted \n.
					else:
						if not self.__fullStateCache['inField'] and '\n' != self.__curToken[1]:
							self.__appendToCurrentParagraph(self.__curToken[1])

				self.__prevToken = self.__curToken
				self.__curToken = self.__getNextToken()

