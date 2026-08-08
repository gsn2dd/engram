# Friendly entry points, installed system-wide via /etc/profile.d so they exist
# for any user on the box rather than only for whoever's ~/.bash_profile was
# edited — including a user created later.
#
# All three run the SAME command. engram-help is the real thing; these are the
# names someone might actually guess after logging into an unfamiliar server.
# They point at the command rather than at a static text file on purpose: the
# guide adapts to what the box needs (it does not explain how to set a key that
# is already set), and a second copy in a .txt would drift out of date the first
# time anything changed.
alias get_started='engram-help'
alias get-started='engram-help'
alias readme='engram-help'
