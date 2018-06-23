# -*- coding: utf-8 -*-

from .state import ParseState

class MainState(ParseState):

	def _parseControl(self, word, param):

		if (
			# We'll treat the value of \*\generator as a document attribute.
			'\*' == self.parser._prevToken[1] and word == '\\generator'
		) or (
			# Proprietary to LibreOffice / OpenOffice, and I can't even find
			# documentation for what it's supposed to do, so just skip over it.
			'\*' == self.parser._prevToken[1] and word == '\\pgdsctbl':
		) or (
			# Skip over these sections. We're not going to use them (at least
			# for now.)
			TokenType.OPEN_BRACE == self.parser._prevToken[0] and (
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
			)
		):
			state = GroupSkipState()
			state.parse()
			return True

		# Beginning of a field
		elif TokenType.OPEN_BRACE == self.parser._prevToken[0] and '\\field' == word:
			state = FieldState()
			state.parse()
			return True

		# We've entered an embedded image.
		elif TokenType.OPEN_BRACE == self.parser._prevToken[0] and '\\pict' == word:
			state = PictState()
			state.parse()
			return True

		else:
			return super()._parseControl(word, param)

	###########################################################################

	def _parseCharacter(self, token):

		if '\n' != self.parser._curToken[1]:
			self.parser._appendToCurrentParagraph(self.parser._curToken[1])

		return True
